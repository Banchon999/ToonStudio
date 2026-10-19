"""The Segment step's red mask must stay on the lettering.

Reported: Segment spreads onto other parts of the page and has to be erased by
hand every time. Measured on seven real webtoon pages: the strokes came from
thresholding each detected box, because Segment only *peeked* at the text
model's prediction, which is not cached until Clean has run — and Segment runs
before Clean. Thresholding takes whatever is dark or light inside the box as
lettering: the ornaments in a caption box's corners, smoke and ink spatter
behind narration, part of an SFX next to a bubble. 12% of the stroke pixels
sat off the lettering, against 5% with the model's prediction, which Clean
already uses. Segment now computes that prediction on its worker.

The page here reproduces the real case: lettering with textured smoke behind
it inside the same text box.
"""

import numpy as np
import pytest
from PySide6.QtCore import QPointF

from modules.utils.textblock import TextBlock

H, W = 220, 320


def make_page():
    rng = np.random.default_rng(0)
    page = np.full((H, W, 3), 225, np.uint8)
    yy, xx = np.mgrid[0:H, 0:W]
    smoke = ((xx - 150) ** 2 / 90 ** 2 + (yy - 158) ** 2 / 22 ** 2) < 1
    noise = rng.integers(40, 200, (H, W))
    page[smoke] = np.stack([noise] * 3, -1)[smoke]
    letters = np.zeros((H, W), bool)
    for y in (50, 90):
        for k in range(9):
            x = 50 + k * 24
            page[y:y + 22, x:x + 4] = 20
            page[y:y + 4, x:x + 14] = 20
            page[y + 18:y + 22, x:x + 14] = 20
            letters[y:y + 22, x:x + 14] = True
    prediction = np.where(letters, 255, 0).astype(np.uint8)   # what the text model sees
    return page, smoke, letters, prediction


def block():
    return TextBlock(text_bbox=np.array([30, 35, 290, 185]), text_class="text_free")


def covered(stroke, region, offset=(0, 0)):
    """Share of region's pixels inside the stroke's path."""
    path = stroke["path"]
    ys, xs = np.nonzero(region)
    step = max(1, len(xs) // 300)
    hits = [path.contains(QPointF(x + offset[0] + 0.5, y + offset[1] + 0.5))
            for x, y in zip(xs[::step], ys[::step])]
    return sum(hits) / len(hits)


@pytest.fixture
def viewer(qapp):
    from app.ui.canvas.image_viewer import ImageViewer

    page, *_ = make_page()
    view = ImageViewer(None)
    view.resize(400, 300)
    view.display_image_array(page)
    yield view
    view.close()


def test_thresholding_alone_paints_the_smoke(viewer):
    # The cause, kept so the reason for the model is not forgotten.
    page, smoke, letters, _ = make_page()
    stroke = viewer.drawing_manager.make_segmentation_stroke_data(block(), page)
    assert covered(stroke, smoke) > 0.5


def test_with_the_model_prediction_only_the_lettering_is_painted(viewer):
    page, smoke, letters, prediction = make_page()
    stroke = viewer.drawing_manager.make_segmentation_stroke_data(block(), page, page_text_mask=prediction)
    assert covered(stroke, letters) > 0.95
    assert covered(stroke, smoke) < 0.02


def test_a_block_the_model_sees_no_lettering_in_gets_no_stroke(viewer):
    # On a real page: artwork the detector took for text. A rectangle over it
    # was the old fallback.
    page, smoke, _, _ = make_page()
    art_only = TextBlock(text_bbox=np.array([250, 188, 310, 214]), text_class="text_free")
    stroke = viewer.drawing_manager.make_segmentation_stroke_data(
        art_only, page, page_text_mask=np.zeros((H, W), np.uint8))
    assert stroke is None


def test_the_segment_button_computes_the_prediction_on_its_worker(viewer, monkeypatch):
    from types import SimpleNamespace
    from app.controllers import manual_workflow
    from app.controllers.manual_workflow import ManualWorkflowController

    page, smoke, letters, prediction = make_page()
    calls = []

    def fake_segment_page(image, settings):
        calls.append(image.shape)
        return prediction

    monkeypatch.setattr(manual_workflow, "segment_page", fake_segment_page)
    ctrl = ManualWorkflowController.__new__(ManualWorkflowController)
    ctrl.main = SimpleNamespace(image_viewer=viewer, settings_page=object())
    results = ctrl._segmentation_strokes([block(), block()], page)
    assert len(calls) == 1                     # once per page, not per block
    assert all(covered(s, smoke) < 0.02 for _, s in results)
    assert all(covered(s, letters) > 0.95 for _, s in results)


def test_webtoon_strokes_use_the_visible_slice_and_land_in_the_scene(viewer, monkeypatch):
    from types import SimpleNamespace
    from pipeline import segmentation_handler
    from pipeline.segmentation_handler import SegmentationHandler

    page, smoke, letters, prediction = make_page()
    blk = block()
    scene_xyxy = blk.xyxy.copy() + np.array([0, 1000, 0, 1000])

    def fake_filter(main_page, pipeline, mappings, single_block=False):
        # As the real helper does: visible-slice coordinates now, scene ones kept.
        blk._original_xyxy = scene_xyxy.copy()
        blk._original_bubble_xyxy = None
        blk._mapping, blk._page_index = mappings[0], 0
        return [blk]

    seen = []
    monkeypatch.setattr(segmentation_handler, "filter_and_convert_visible_blocks", fake_filter)
    monkeypatch.setattr(segmentation_handler, "segment_page",
                        lambda image, settings: seen.append(image.shape) or prediction)
    fake_viewer = SimpleNamespace(
        hasPhoto=lambda: True,
        get_visible_area_image=lambda: (page, [{"scene_y_start": 1000}]),
        drawing_manager=viewer.drawing_manager,
    )
    main = SimpleNamespace(image_viewer=fake_viewer, webtoon_mode=True, settings_page=object())
    results = SegmentationHandler(main, None).segment_webtoon_visible_area()
    assert seen == [page.shape]
    [(got_blk, stroke)] = results
    assert got_blk is blk and list(blk.xyxy) == list(scene_xyxy)   # coordinates restored
    assert covered(stroke, letters, offset=(0, 1000)) > 0.95       # placed in the scene
    assert covered(stroke, smoke, offset=(0, 1000)) < 0.02
