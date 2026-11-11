"""The chapter queue through the real window, with the models faked.

Three chapters (two folders of images and a series folder's worth) go in;
out come a project and the translated pages per chapter, each chapter's
translation from its own pages, and a progress file that lets the next run
skip what is finished.
"""

import json
import os
import re

import numpy as np
import pytest
from PIL import Image

from core import chapter_queue as cq
from modules.translation.llm.base import BaseLLMTranslation
from modules.utils.textblock import TextBlock


def _pump_until(qapp, condition, timeout_ms=60000):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        qapp.processEvents()
    return condition()


class FakeLLM(BaseLLMTranslation):
    def get_system_prompt(self, source_lang, target_lang):
        return ""

    def identify_speakers(self, blk_list, image):
        return None

    def _perform_translation(self, user_prompt, system_prompt, image):
        blocks = json.loads(re.search(r"\{[\s\S]*\}", user_prompt.split("Translate this:")[-1]).group(0))
        return json.dumps({k: f"แปล:{v}" for k, v in blocks.items()}, ensure_ascii=False)


class FakeDetector:
    def detect(self, image):
        return [TextBlock(text_bbox=np.array([20, 20, 140, 60]), text_class="text_free")]


class FakeOCR:
    def initialize(self, main, lang):
        pass

    def process(self, image, blk_list):
        for blk in blk_list:
            blk.text = f"글자{int(image[0, 0, 0])}"


def _page(path, marker):
    page = np.full((200, 300, 3), 230, np.uint8)
    page[0, 0] = marker                          # tells FakeOCR which page it reads
    page[30:50, 30:130] = 20
    Image.fromarray(page).save(path)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    import controller as controller_mod
    from app.controllers import manual_workflow, text as text_mod
    from modules.translation import factory
    from app import validation

    monkeypatch.setattr(factory.TranslationFactory, "create_engine",
                        classmethod(lambda cls, *a, **k: FakeLLM()))
    for module in (manual_workflow, validation):
        monkeypatch.setattr(module, "validate_translator", lambda *a, **k: True)
        monkeypatch.setattr(module, "validate_ocr", lambda *a, **k: True)
    monkeypatch.setattr(validation, "font_selected", lambda main: True)
    monkeypatch.setattr(manual_workflow, "OCRProcessor", FakeOCR)
    monkeypatch.setattr(manual_workflow, "segment_page", lambda image, settings: None)
    monkeypatch.setattr(text_mod, "font_selected", lambda main: True)
    finished = []
    from app.ui.messages import Messages
    monkeypatch.setattr(Messages, "show_chapter_queue_done",
                        staticmethod(lambda parent, *a, **k: finished.append((a, k))))

    win = controller_mod.ComicTranslate()
    win.pipeline.block_detection.block_detector_cache = FakeDetector()
    win.pipeline.inpainting.inpaint_image = lambda image, mask, config, blk_list=None: np.where(
        mask[..., None] > 0, 255, image).astype(np.uint8)
    glossary = win.settings_page.ui.glossary_page.manager
    glossary.save = lambda: None
    glossary.enabled = False

    series = tmp_path / "series"
    marker = 1
    for chapter in ("ep 1", "ep 2", "ep 10"):
        os.makedirs(series / chapter)
        for index in range(2):
            _page(str(series / chapter / f"{index:02d}.png"), marker)
            marker += 1
    yield win, str(series), str(tmp_path / "out"), finished
    win._skip_close_prompt = True
    win.close()


def _run_queue(win, qapp, chapters, out, **kw):
    assert win.chapter_queue_ctrl.start(chapters, out, **kw)
    assert _pump_until(qapp, lambda: not win.chapter_queue_ctrl.running, 120000)


def test_three_chapters_become_three_projects_with_their_own_pages(window, qapp):
    win, series, out, finished = window
    chapters = cq.make_chapters(cq.find_chapters(series))
    assert [c.name for c in chapters] == ["ep 1", "ep 2", "ep 10"]

    _run_queue(win, qapp, chapters, out, mode="smart", export_format="folder")

    assert [c.status for c in chapters] == [cq.DONE] * 3, [(c.status, c.detail) for c in chapters]
    assert [c.pages for c in chapters] == [2, 2, 2]
    for chapter in chapters:
        assert os.path.isfile(os.path.join(out, f"{chapter.name}.ctpr"))
        exported = sorted(os.listdir(os.path.join(out, chapter.name)))
        assert exported == ["00.png", "01.png"], (chapter.name, exported)
    # The last chapter is the one left open, and its blocks are its own.
    assert win.project_file == os.path.join(out, "ep 10.ctpr")
    assert len(win.image_files) == 2
    texts = sorted(b.translation for p in win.image_files for b in win.image_states.blk_list(p))
    assert texts == ["แปล:글자5", "แปล:글자6"]
    # The exported page is the finished one: the fake lettering (a flat block
    # of grey 20) was cleaned away and the translation drawn in its place.
    source = np.asarray(Image.open(os.path.join(series, "ep 1", "00.png")).convert("RGB"))
    page = np.asarray(Image.open(os.path.join(out, "ep 1", "00.png")).convert("RGB"))
    assert (source[30:50, 30:130] == 20).all(axis=-1).sum() == 2000
    assert (page[30:50, 30:130] == 20).all(axis=-1).sum() < 200
    assert not np.array_equal(page, source)
    progress = cq.load_progress(out)
    assert {k: v["status"] for k, v in progress.items()} == {"ep 1": "done", "ep 2": "done", "ep 10": "done"}
    assert finished and finished[-1][0][:4] == (3, 0, 0, 0)

    # Run again: everything is finished, nothing runs.
    again = cq.make_chapters(cq.find_chapters(series))
    _run_queue(win, qapp, again, out, mode="smart", export_format="none")
    assert [c.status for c in again] == [cq.SKIPPED] * 3


def test_the_batch_mode_runs_each_chapter_through_the_batch(window, qapp, monkeypatch):
    win, series, out, finished = window
    ran = []

    def fake_batch(paths=None):
        ran.append(list(paths or win.image_files))
        for path in win.image_files:
            blk = TextBlock(text_bbox=np.array([20, 20, 140, 60]), text_class="text_free", text="x")
            blk.translation = os.path.basename(os.path.dirname(path))
            win.image_states.get_page_state(path)["blk_list"] = [blk]

    monkeypatch.setattr(win.pipeline, "batch_process", fake_batch)
    chapters = cq.make_chapters(cq.find_chapters(series))[:2]
    _run_queue(win, qapp, chapters, out, mode="batch", export_format="cbz")

    assert [c.status for c in chapters] == [cq.DONE, cq.DONE], [(c.status, c.detail) for c in chapters]
    assert [len(r) for r in ran] == [2, 2]
    assert {os.path.basename(os.path.dirname(r[0])) for r in ran} == {"ep 1", "ep 2"}
    for name in ("ep 1", "ep 2"):
        assert os.path.isfile(os.path.join(out, f"{name}.cbz"))
        assert os.path.isfile(os.path.join(out, f"{name}.ctpr"))


def test_stop_saves_the_current_chapter_and_leaves_the_rest(window, qapp):
    win, series, out, finished = window
    chapters = cq.make_chapters(cq.find_chapters(series))
    ctrl = win.chapter_queue_ctrl
    # Stop as soon as the first chapter's run begins.
    real_start = ctrl._start_run

    def start_then_stop():
        real_start()
        ctrl.cancel()

    ctrl._start_run = start_then_stop
    _run_queue(win, qapp, chapters, out, mode="smart", export_format="none")

    assert chapters[0].status == cq.STOPPED
    assert [c.status for c in chapters[1:]] == [cq.PENDING, cq.PENDING]
    assert os.path.isfile(os.path.join(out, "ep 1.ctpr"))
    assert not cq.already_done(out, chapters[0])
    assert finished[-1][1].get("stopped") is True


def test_each_chapter_also_gets_editable_psds_when_asked(window, qapp):
    # Read back with psd-tools, not the PhotoshopAPI that wrote them: the
    # writer agreeing with itself proves nothing (CLAUDE.md, PSD export).
    from psd_tools import PSDImage

    win, series, out, finished = window
    chapters = cq.make_chapters(cq.find_chapters(series))[:2]
    _run_queue(win, qapp, chapters, out, mode="smart", export_format="folder", export_psd=True)

    assert [c.status for c in chapters] == [cq.DONE, cq.DONE], [(c.status, c.detail) for c in chapters]
    for chapter, first_marker in zip(chapters, (1, 3)):
        folder = cq.psd_path(out, chapter)
        assert sorted(os.listdir(folder)) == ["00.psd", "01.psd"], chapter.name
        # The images still go to their own folder, not mixed with the PSDs.
        assert sorted(os.listdir(os.path.join(out, chapter.name))) == ["00.png", "01.png"]
        psd = PSDImage.open(os.path.join(folder, "00.psd"))
        assert (psd.width, psd.height) == (300, 200)
        texts = [layer.text for layer in psd.descendants() if layer.kind == "type"]
        # The chapter's own translation, as an editable text layer.
        assert texts == [f"แปล:글자{first_marker}"], (chapter.name, texts)


def test_no_psd_folder_unless_asked(window, qapp):
    win, series, out, finished = window
    chapters = cq.make_chapters(cq.find_chapters(series))[:1]
    _run_queue(win, qapp, chapters, out, mode="smart", export_format="none")
    assert chapters[0].status == cq.DONE
    assert not os.path.exists(cq.psd_path(out, chapters[0]))


# -- Automatic run: a PSD per page as it finishes, one folder per chapter -----

def test_page_psd_folder_sits_beside_the_chapter(tmp_path):
    page = str(tmp_path / "series" / "ep 1" / "001.png")
    assert cq.page_psd_folder(page) == str(tmp_path / "series" / "ep 1-PSD")
    archive = str(tmp_path / "series" / "ep 2.cbz")
    assert cq.page_psd_folder(str(tmp_path / "tmpx" / "01.png"), archive) == \
        str(tmp_path / "series" / "ep 2-PSD")


def test_an_automatic_run_writes_each_pages_psd_beside_its_chapter(window, qapp, monkeypatch):
    """Two chapter folders in one project, as the workspace's "+ Folder" adds
    them: each page's PSD lands in its own chapter's "-PSD" folder while the
    batch is still running, carrying that page's translation."""
    from psd_tools import PSDImage

    win, series, out, finished = window
    paths = cq.images_in(os.path.join(series, "ep 1")) + cq.images_in(os.path.join(series, "ep 2"))
    win.image_ctrl.thread_load_images(paths)
    assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto() and len(win.image_files) == 4)
    # Real rendered text items on every page, from Smart Workflow.
    assert win.smart_ctrl.start()
    assert _pump_until(qapp, lambda: not win.smart_ctrl.running)

    win.settings_page.ui.psd_checkbox.setChecked(True)
    seen_during_batch = []

    def fake_batch(selected=None):
        # What batch_process does per page once it is rendered.
        for path in list(win.image_files):
            win.render_state_ready.emit(path)

    monkeypatch.setattr(win.pipeline, "batch_process", fake_batch)
    real_finished = win.on_batch_process_finished

    def finished_hook():
        seen_during_batch.append(win._batch_active)
        real_finished()

    monkeypatch.setattr(win, "on_batch_process_finished", finished_hook)
    win.start_batch_process()
    assert _pump_until(qapp, lambda: seen_during_batch and win.batch_psd_ctrl.idle(), 120000)

    exporter = win.batch_psd_ctrl
    assert exporter.failures == []
    for chapter, markers in (("ep 1", (1, 2)), ("ep 2", (3, 4))):
        folder = os.path.join(series, f"{chapter}-PSD")
        assert sorted(os.listdir(folder)) == ["00.psd", "01.psd"], chapter
        for name, marker in zip(("00.psd", "01.psd"), markers):
            psd = PSDImage.open(os.path.join(folder, name))
            texts = [layer.text for layer in psd.descendants() if layer.kind == "type"]
            assert texts == [f"แปล:글자{marker}"], (chapter, name, texts)
    # The source chapters are untouched and the PSD folders are no chapters.
    assert [os.path.basename(c) for c in cq.find_chapters(series)] == ["ep 1", "ep 2", "ep 10"]


def test_no_page_psds_unless_the_setting_is_on(window, qapp, monkeypatch):
    win, series, out, finished = window
    paths = cq.images_in(os.path.join(series, "ep 1"))
    win.image_ctrl.thread_load_images(paths)
    assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto() and len(win.image_files) == 2)
    win.settings_page.ui.psd_checkbox.setChecked(False)
    done = []
    monkeypatch.setattr(win.pipeline, "batch_process",
                        lambda selected=None: [win.render_state_ready.emit(p) for p in list(win.image_files)])
    real_finished = win.on_batch_process_finished
    monkeypatch.setattr(win, "on_batch_process_finished", lambda: (done.append(1), real_finished()))
    win.start_batch_process()
    assert _pump_until(qapp, lambda: done)
    assert not os.path.exists(os.path.join(series, "ep 1-PSD"))
