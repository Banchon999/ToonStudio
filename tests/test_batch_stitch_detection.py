"""Blocks detected with neighbouring pages stitched on stay usable boxes.

Reported from the 3.2.0-beta.10 Windows build: a batch run died at Clean with
"TypeError: slice indices must be integers or None" in build_block_mask_data.
With "stitch neighbouring pages for detection" on and pages of one width (a
long strip cut into slices), every block is moved back from the stitched canvas
by _shift_block_vertical, which handed back its box as floats; OCR casts its own
crop, so the first thing to slice the page with the box was the mask.
"""

import types

import numpy as np

from modules.utils.image_utils import build_block_mask_data, generate_mask
from modules.utils.textblock import TextBlock
from pipeline.batch_processor import BatchProcessor


def _page(value):
    page = np.full((300, 200, 3), 235, np.uint8)
    page[0, 0] = value
    return page


class CanvasDetector:
    """Finds one block of lettering in the middle of whatever it is shown."""

    def __init__(self):
        self.seen = []

    def detect(self, image):
        self.seen.append(image.shape)
        mid = image.shape[0] // 2
        blk = TextBlock(text_bbox=np.array([40, mid - 20, 160, mid + 20]),
                        text_class="text_bubble")
        blk.bubble_xyxy = np.array([20, mid - 40, 180, mid + 40])
        blk.lines = [[40, mid - 20, 160, mid + 20]]
        return [blk]


def _processor(tmp_path, detector):
    import imkit as imk

    paths = []
    for i in range(3):
        path = str(tmp_path / f"{i:03d}.png")
        imk.write_image(path, _page(i + 1))
        paths.append(path)
    checkbox = types.SimpleNamespace(isChecked=lambda: True)
    proc = BatchProcessor.__new__(BatchProcessor)
    proc.block_detection = types.SimpleNamespace(block_detector_cache=detector)
    proc.main_page = types.SimpleNamespace(
        settings_page=types.SimpleNamespace(ui=types.SimpleNamespace(stitch_detection_checkbox=checkbox))
    )
    return proc, paths


def test_a_block_found_on_the_stitched_canvas_comes_back_with_integer_boxes(tmp_path):
    detector = CanvasDetector()
    proc, paths = _processor(tmp_path, detector)
    image = _page(2)
    blocks = proc._detect_blocks_for_batch(paths, 1, image)

    assert detector.seen[0][0] > image.shape[0]  # the neighbours really were stitched on
    assert len(blocks) == 1
    blk = blocks[0]
    for box in (blk.xyxy, blk.bubble_xyxy, *blk.lines):
        assert all(isinstance(v, (int, np.integer)) for v in box), box
    assert list(blk.xyxy) == [40, 130, 160, 170]  # back in the page's own rows


def test_the_clean_mask_is_built_from_a_stitched_block(tmp_path):
    proc, paths = _processor(tmp_path, CanvasDetector())
    image = _page(2)
    image[140:160, 50:150] = 20  # the lettering
    blk = proc._detect_blocks_for_batch(paths, 1, image)[0]
    blk.text, blk.translation = "글자", "คำ"
    mask = generate_mask(image, [blk], default_padding=5, bubble_inset=7, page_text_mask=None)
    assert mask is not None and mask[150, 100] > 0


def test_a_float_box_from_anywhere_still_crops(tmp_path):
    # The webtoon chunk path moves boxes by float offsets too; the mask must
    # not depend on every caller remembering to round.
    image = np.full((200, 200, 3), 235, np.uint8)
    image[90:110, 60:140] = 20
    blk = TextBlock(text_bbox=np.array([50.0, 80.4, 150.0, 120.6]), text_class="text_free")
    blk.text = "x"
    crop_mask, bounds = build_block_mask_data(image, blk, default_padding=5)
    assert crop_mask is not None
    assert all(isinstance(v, (int, np.integer)) for v in bounds)
