"""Free text that glows is cleaned with its glow.

Found when tall webtoon pages started being segmented in page-shaped windows:
the sharper prediction hugs white lettering, and over a dark, textured panel
`fit_mask_growth` (which grows only while the border stays on flat pixels)
found every candidate border busy and kept the mask at the letters' edge — so
the inpainter rebuilt the glow as a grey ghost of the words ("ABSOLUTELY
CANNOT", a "LUACOMIC.ORG" watermark). Ordinary pages were always segmented
that sharply. Bubbles are not affected: they are dilated a fixed amount inside
their outline.
"""

import numpy as np
import pytest
from PIL import Image, ImageFilter

from modules.utils import image_utils
from modules.utils.image_utils import build_block_mask_data, glow_reach
from modules.utils.textblock import TextBlock

LETTERS = (slice(100, 124), slice(80, 320))


def letters_mask(shape=(240, 400)):
    """Block capitals: 24 px tall bars with gaps, like a line of a caption."""
    mask = np.zeros(shape, bool)
    for x in range(80, 320, 20):
        mask[100:124, x:x + 14] = True
        mask[106:118, x + 5:x + 9] = False
    return mask


def glowing_caption(glow_sigma=4.0, glow=True, letter=(252, 252, 250), back=(40, 26, 24), seed=0):
    rng = np.random.default_rng(seed)
    mask = letters_mask()
    page = np.empty(mask.shape + (3,), float)
    page[:] = back
    page += rng.normal(0, 6, page.shape)  # a textured panel, never flat
    if glow:
        halo = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(glow_sigma))).astype(float) / 255
        halo = np.clip(halo * 1.6, 0, 1)
        page = page * (1 - halo[..., None]) + np.array(letter) * halo[..., None] * 0.85 + page * 0.15 * halo[..., None]
    page[mask] = letter
    return np.clip(page, 0, 255).astype(np.uint8), mask


def outer_glow(page, mask, back=(40, 26, 24), letter=(252, 252, 250)):
    """The glow's faint outer part: 8-30% of the way from the panel to the
    letters' colour. Its bright inner part reads as lettering and was always
    cleaned; this is what was left as a ghost."""
    axis = np.array(letter, float) - back
    t = ((page.astype(float) - back) @ axis) / (axis @ axis)
    return (t >= 0.08) & (t < 0.3) & ~mask


def free_block():
    blk = TextBlock(text_bbox=np.array([78, 98, 322, 126]))
    blk.text_class = "text_free"
    blk.text = "x"
    return blk


def mask_in_page(page, blk, prediction):
    crop_mask, (x1, y1, x2, y2) = build_block_mask_data(page, blk, default_padding=5, page_text_mask=prediction)
    full = np.zeros(page.shape[:2], bool)
    full[y1:y2, x1:x2] = crop_mask > 0
    return full


class TestGlowReach:
    def test_a_glow_is_followed_until_it_fades(self):
        page, mask = glowing_caption()
        assert 5 <= glow_reach(page, mask) <= 12

    def test_a_wider_glow_reaches_farther(self):
        page_narrow, mask = glowing_caption(glow_sigma=2.0)
        page_wide, _ = glowing_caption(glow_sigma=5.0)
        assert glow_reach(page_wide, mask) > glow_reach(page_narrow, mask)

    def test_letters_without_a_glow_have_none(self):
        page, mask = glowing_caption(glow=False)
        assert glow_reach(page, mask) <= 1

    def test_dark_lettering_on_paper_has_none(self):
        page, mask = glowing_caption(glow=False, letter=(40, 38, 36), back=(240, 236, 230))
        assert glow_reach(page, mask) <= 1

    def test_letters_the_colour_of_their_background_are_left_alone(self):
        page, mask = glowing_caption(letter=(90, 80, 80), back=(60, 52, 50))
        assert glow_reach(page, mask) == 0

    def test_artwork_beside_the_letters_is_not_a_glow(self):
        # A bright shape touching one side of the line does not fade around it.
        page, mask = glowing_caption(glow=False)
        page[90:134, 60:80] = (250, 250, 250)
        assert glow_reach(page, mask) <= 1


class TestCleanMask:
    def test_the_glow_is_inside_the_free_text_mask(self):
        page, mask = glowing_caption()
        full = mask_in_page(page, free_block(), (mask * 255).astype(np.uint8))
        assert full[mask].all()
        assert full[outer_glow(page, mask)].mean() >= 0.95

    def test_without_it_the_glow_is_left_behind(self, monkeypatch):
        # What Clean did before: the border is never flat over the panel, so
        # the mask stopped at the letters' edge.
        monkeypatch.setattr(image_utils, "glow_reach", lambda *a, **k: 0)
        page, mask = glowing_caption()
        full = mask_in_page(page, free_block(), (mask * 255).astype(np.uint8))
        assert full[outer_glow(page, mask)].mean() < 0.5

    def test_the_mask_reaches_past_the_block_crop_when_the_glow_does(self):
        page, mask = glowing_caption(glow_sigma=5.0)
        blk = free_block()
        _, (x1, y1, x2, y2) = build_block_mask_data(page, blk, page_text_mask=(mask * 255).astype(np.uint8))
        assert y1 < 98 - 10 or y2 > 126 + 10 or x1 < 78 - 10 or x2 > 322 + 10

    def test_no_glow_leaves_the_mask_as_it_was(self, monkeypatch):
        page, mask = glowing_caption(glow=False, letter=(40, 38, 36), back=(240, 236, 230))
        prediction = (mask * 255).astype(np.uint8)
        with_glow = build_block_mask_data(page, free_block(), page_text_mask=prediction)
        monkeypatch.setattr(image_utils, "glow_reach", lambda *a, **k: 0)
        without = build_block_mask_data(page, free_block(), page_text_mask=prediction)
        assert with_glow[1] == without[1]
        assert np.array_equal(with_glow[0], without[0])

    def test_bubbles_are_not_measured_for_a_glow(self, monkeypatch):
        def refuse(*a, **k):
            pytest.fail("a bubble's mask is bounded by its outline, not grown over a glow")

        monkeypatch.setattr(image_utils, "glow_reach", refuse)
        page, mask = glowing_caption()
        blk = free_block()
        blk.text_class = "text_bubble"
        blk.bubble_xyxy = np.array([40, 60, 360, 170])
        crop_mask, _ = build_block_mask_data(page, blk, clip_to_bubble=True,
                                             page_text_mask=(mask * 255).astype(np.uint8))
        assert crop_mask is not None
