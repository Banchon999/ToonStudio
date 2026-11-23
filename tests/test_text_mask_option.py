"""comic-text-mask as the other text segmentation model (modules/detection/text_mask_onnx.py).

Through the app's own path (segment_page -> generate_mask -> Clean with AOT) on the
three Korean test pages, Hayai still read 3 Hangul letters after cleaning with the
default model and none with comic-text-mask; segmentation took 1.8 s against 4.6 s.
"""
import ast
import os

import numpy as np
import pytest

from modules.detection import text_mask_onnx as tm
from modules.utils import text_segmentation as ts


class FakeSession:
    """Answers "all text" and counts the crops it was given."""

    def __init__(self):
        self.calls = 0

    def get_inputs(self):
        return [type("I", (), {"name": "image"})()]

    def run(self, _outputs, feeds):
        self.calls += 1
        square = feeds["image"]
        assert square.dtype == np.uint8 and square.shape == (1, 3, tm.INPUT_SIZE, tm.INPUT_SIZE)
        return [np.ones((1, 1, tm.INPUT_SIZE, tm.INPUT_SIZE), np.float32)]


@pytest.fixture
def masker():
    m = tm.ComicTextMasker()
    m.session = FakeSession()
    return m


def test_crops_have_room_round_the_box_and_stay_on_the_page():
    assert tm.crop_bounds([100, 100, 200, 140], (500, 400)) == (85, 92, 215, 148)
    assert tm.crop_bounds([0, 0, 20, 20], (30, 30)) == (0, 0, 28, 28)


def test_letterbox_keeps_proportions_at_the_top_left():
    square, nh, nw = tm.letterbox(np.full((50, 200, 3), 200, np.uint8))
    assert (nh, nw) == (96, 384)
    assert square[:nh, :nw].min() == 200 and square[nh:].max() == 0


class TestPageMap:
    def test_every_box_is_read_once_per_page(self, masker):
        page = np.random.default_rng(0).integers(0, 255, (400, 300, 3), dtype=np.uint8)
        boxes = [[20, 20, 80, 60], [150, 200, 250, 260]]
        first = masker.page_map(page, boxes)
        assert masker.session.calls == 2
        again = masker.page_map(page, boxes[1:])
        assert masker.session.calls == 2, "a box already read is not read again"
        assert np.array_equal(first, again), "the map holds every box read on the page"

    def test_only_the_boxes_are_marked(self, masker):
        page = np.zeros((400, 300, 3), np.uint8)
        page[0, 0] = 1
        result = masker.page_map(page, [[100, 100, 150, 150]])
        x1, y1, x2, y2 = tm.crop_bounds([100, 100, 150, 150], page.shape)
        assert result[y1:y2, x1:x2].min() == 255
        result[y1:y2, x1:x2] = 0
        assert result.max() == 0

    def test_a_new_page_forgets_the_old_one(self, masker):
        a = np.zeros((200, 200, 3), np.uint8)
        b = np.full((200, 200, 3), 9, np.uint8)
        masker.page_map(a, [[10, 10, 50, 50]])
        assert masker.peek(b) is None
        masker.page_map(b, [[10, 10, 50, 50]])
        assert masker.session.calls == 2 and masker.peek(a) is None


class TestChoosingTheModel:
    @pytest.fixture
    def models(self, monkeypatch):
        used = []
        from modules.detection import text_seg_onnx

        class Seg:
            def segment_cached(self, image):
                used.append("ctd")
                return np.full(image.shape[:2], 1, np.uint8)

        class Mask:
            def page_map(self, image, boxes):
                used.append(("ctm", len(boxes)))
                return np.full(image.shape[:2], 2, np.uint8)

        monkeypatch.setattr(text_seg_onnx, "get_segmenter", lambda device="cpu": Seg())
        monkeypatch.setattr(tm, "get_masker", lambda device="cpu": Mask())
        return used

    @staticmethod
    def settings(engine, enabled=True):
        return type("S", (), {
            "get_use_text_segmentation_model": lambda s: enabled,
            "get_text_segmentation_engine": lambda s: engine,
            "is_gpu_enabled": lambda s: False,
        })()

    @staticmethod
    def blocks(n):
        return [type("B", (), {"xyxy": np.array([5, 5, 40, 40])})() for _ in range(n)]

    def test_the_default_reads_the_whole_page(self, models):
        image = np.zeros((60, 60, 3), np.uint8)
        assert ts.segment_page(image, self.settings("ctd"), self.blocks(2))[0, 0] == 1
        assert models == ["ctd"]

    def test_comic_text_mask_reads_the_boxes(self, models):
        image = np.zeros((60, 60, 3), np.uint8)
        assert ts.segment_page(image, self.settings("ctm"), self.blocks(3))[0, 0] == 2
        assert models == [("ctm", 3)]

    def test_without_boxes_it_falls_back_to_the_whole_page_model(self, models):
        image = np.zeros((60, 60, 3), np.uint8)
        assert ts.segment_page(image, self.settings("ctm"), None)[0, 0] == 1
        assert models == ["ctd"]

    def test_a_failing_mask_model_falls_back_to_the_whole_page_model(self, models, monkeypatch):
        def broken(device="cpu"):
            raise RuntimeError("download failed")

        monkeypatch.setattr(tm, "get_masker", broken)
        image = np.zeros((60, 60, 3), np.uint8)
        assert ts.segment_page(image, self.settings("ctm"), self.blocks(1))[0, 0] == 1

    def test_switched_off_means_thresholding_whichever_model(self, models):
        image = np.zeros((60, 60, 3), np.uint8)
        assert ts.segment_page(image, self.settings("ctm", enabled=False), self.blocks(1)) is None
        assert models == []

    def test_an_unknown_value_is_the_default(self):
        assert ts.segmentation_engine(self.settings("something")) == ts.WHOLE_PAGE
        assert ts.segmentation_engine(object()) == ts.WHOLE_PAGE


def test_every_caller_hands_over_its_blocks():
    """The per-box model sees only what it is given; a caller passing no blocks
    would silently get the whole-page model instead."""
    root = os.path.dirname(os.path.dirname(__file__))
    callers = ["app/controllers/manual_workflow.py", "app/controllers/paint.py",
               "pipeline/webtoon_batch/chunk.py", "pipeline/segmentation_handler.py",
               "pipeline/inpainting.py", "pipeline/batch_processor.py"]
    for rel in callers:
        tree = ast.parse(open(os.path.join(root, rel), encoding="utf-8").read())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", getattr(n.func, "attr", None)) == "segment_page"]
        assert calls, rel
        for call in calls:
            assert len(call.args) == 3, f"{rel}:{call.lineno} passes no blocks"


def test_idle_release_lets_the_mask_model_go():
    from pipeline.main_pipeline import ComicTranslatePipeline

    tm._masker = object()
    pipeline = ComicTranslatePipeline.__new__(ComicTranslatePipeline)
    pipeline.block_detection = type("B", (), {"block_detector_cache": None})()
    pipeline.inpainting = type("I", (), {"inpainter_cache": None, "cached_inpainter_key": None})()
    pipeline.release_model_caches()
    assert tm._masker is None


def test_the_model_file_is_pinned():
    from modules.utils.download import ModelDownloader, ModelID

    spec = ModelDownloader.registry[ModelID.COMIC_TEXT_MASK_ONNX]
    assert spec.files == ["model.onnx"] and len(spec.sha256[0]) == 64
    assert "/resolve/5ca91878" in spec.url, "a commit, not main"


def test_settings_offer_it_default_off_and_remember_it(qapp):
    from PySide6.QtCore import QSettings

    from app.ui.settings.settings_page import SettingsPage

    page = SettingsPage()
    assert page.get_text_segmentation_engine() == "ctd"
    page.ui.tools_page.set_text_seg_engine("ctm")
    assert page.get_text_segmentation_engine() == "ctm"
    assert page.get_all_settings()["tools"]["text_segmentation_engine"] == "ctm"
    page.ui.text_segmentation_checkbox.setChecked(False)
    assert not page.ui.tools_page.text_seg_engine_widget.isEnabled()
    page.save_settings()
    again = SettingsPage()
    again.load_settings()
    assert again.get_text_segmentation_engine() == "ctm"
    QSettings("ComicLabs", "ComicTranslate").remove("tools/text_segmentation_engine")


def _model_here():
    from modules.utils.download import ModelDownloader, ModelID

    spec = ModelDownloader.registry[ModelID.COMIC_TEXT_MASK_ONNX]
    return os.path.exists(os.path.join(spec.save_dir, "comic-text-mask.onnx"))


@pytest.mark.skipif(not _model_here(), reason="comic-text-mask is not downloaded here")
def test_real_model_marks_the_lettering_of_a_test_bubble():
    from PIL import Image

    page = np.asarray(Image.open(os.path.join(os.path.dirname(__file__), "data", "webtoon_ko",
                                              "page_01.png")).convert("RGB"))
    masker = tm.ComicTextMasker()
    masker.initialize("cpu")
    box = [704, 622, 801, 679]  # "…탑?" in a glowing bubble
    prob = masker.page_map(page, [box])
    inside = prob[622:679, 704:801] > 127
    assert 0.03 < inside.mean() < 0.6, "lettering, not the whole box and not nothing"
    assert (prob[:500] > 127).sum() == 0, "nothing outside the boxes it was given"
