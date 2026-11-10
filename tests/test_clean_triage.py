"""Smart Fill decides, per region, how lettering is removed: white is painted
first, a smooth background is healed, and only texture reaches the model.

The owner's rule: "if a bubble is white, lay the colour first; then say which
parts need the model and which the healing brush"."""

import numpy as np
import pytest

from core import clean_triage, paint
from modules.inpainting.schema import Config
from modules.inpainting.smart_fill import SmartFill


def _text_mask(shape, top=40, left=40):
    mask = np.zeros(shape, np.uint8)
    for x in range(left, left + 80, 12):
        mask[top:top + 24, x:x + 5] = 255
    return mask


def _noisy(image, sigma=1.5, seed=3):
    rng = np.random.default_rng(seed)
    return np.clip(image + rng.normal(0, sigma, image.shape), 0, 255).astype(np.uint8)


class _NoModel:
    """Stands in for LaMa: records what it was asked to inpaint."""

    def __init__(self):
        self.masks = []

    def __call__(self, image, mask, config):
        self.masks.append(mask.copy())
        out = image.copy()
        out[mask > 0] = (1, 2, 3)
        return out


def _used(fill):
    """Which methods the last run used (regions are counted per letter)."""
    return {method for method, count in fill.last_report.items() if count}


@pytest.fixture
def smart_fill():
    fill = SmartFill("cpu")
    fill._fallback_model = _NoModel()
    return fill


class TestTriage:
    def test_white_and_flat_is_painted(self):
        image = _noisy(np.full((100, 160, 3), 250.0))
        region = _text_mask(image.shape[:2]) > 0
        method, colour, _ = clean_triage.triage(image, clean_triage.ring_of(region))
        assert method == clean_triage.COLOUR
        assert all(abs(c - 250) <= 1 for c in colour)

    def test_a_gradient_is_healed_even_when_light(self):
        yy = np.mgrid[:100, :160][0]
        image = _noisy(np.repeat((205 + yy * 0.45)[..., None], 3, axis=2), 0.5)
        region = _text_mask(image.shape[:2]) > 0
        assert clean_triage.triage(image, clean_triage.ring_of(region))[0] == clean_triage.HEAL

    def test_a_flat_colour_that_is_not_white_is_healed(self):
        image = _noisy(np.full((100, 160, 3), (70.0, 110.0, 180.0)))
        region = _text_mask(image.shape[:2]) > 0
        assert clean_triage.triage(image, clean_triage.ring_of(region))[0] == clean_triage.HEAL

    def test_texture_goes_to_the_model(self):
        image = np.full((100, 160, 3), 235, np.uint8)
        image[::4, ::4] = 90
        image[1::4, 1::4] = 90
        region = _text_mask(image.shape[:2]) > 0
        assert clean_triage.triage(image, clean_triage.ring_of(region))[0] == clean_triage.MODEL

    def test_too_little_to_judge_goes_to_the_model(self):
        image = np.full((10, 10, 3), 255, np.uint8)
        ring = np.zeros((10, 10), bool)
        ring[0, :5] = True
        assert clean_triage.triage(image, ring)[0] == clean_triage.MODEL

    def test_the_ring_stays_inside_the_bubble(self):
        region = np.zeros((20, 20), bool)
        region[8:12, 8:12] = True
        within = np.zeros((20, 20), bool)
        within[:, :12] = True
        ring = clean_triage.ring_of(region, 3, within)
        assert ring.any() and not ring[:, 12:].any() and not (ring & region).any()


class TestSmartFill:
    def test_a_white_bubble_is_painted_and_no_model_runs(self, smart_fill):
        page = _noisy(np.full((100, 160, 3), 252.0))
        mask = _text_mask(page.shape[:2])
        page[mask > 0] = 20
        cleaned = smart_fill(page, mask, Config())
        assert _used(smart_fill) == {"colour"}
        assert not smart_fill._fallback_model.masks
        # Painted, not grown from the rim: every cleaned pixel is one colour.
        assert len(np.unique(cleaned[mask > 0].reshape(-1, 3), axis=0)) == 1
        assert cleaned[mask > 0].min() >= 250

    def test_a_tinted_gradient_is_healed_and_no_model_runs(self, smart_fill):
        yy = np.mgrid[:100, :160][0]
        clean = np.stack([60 + yy * 0.8, 90 + yy * 0.6, 150 + yy * 0.3], axis=2)
        page = clean.astype(np.uint8)
        mask = _text_mask(page.shape[:2])
        page[mask > 0] = 245
        cleaned = smart_fill(page, mask, Config())
        assert _used(smart_fill) == {"heal"}
        assert not smart_fill._fallback_model.masks
        error = np.abs(cleaned[mask > 0].astype(int) - clean[mask > 0].astype(int))
        assert error.max() <= 3            # one flat colour would be ~10 off

    def test_lettering_over_texture_reaches_the_model(self, smart_fill):
        page = np.full((100, 160, 3), 235, np.uint8)
        page[::4, ::4] = 90
        page[1::4, 1::4] = 90
        mask = _text_mask(page.shape[:2])
        page[mask > 0] = 20
        cleaned = smart_fill(page, mask, Config())
        assert _used(smart_fill) == {"model"}
        assert len(smart_fill._fallback_model.masks) == 1
        assert (cleaned[mask > 0] == (1, 2, 3)).all()

    def test_a_page_is_sorted_region_by_region(self, smart_fill):
        """White painted, gradient healed, texture inpainted — and the model
        is handed only the textured region."""
        yy = np.mgrid[:100, :160][0]
        white = _noisy(np.full((100, 160, 3), 252.0))
        tint = np.stack([60 + yy * 0.8, 90 + yy * 0.6, 150 + yy * 0.3], axis=2).astype(np.uint8)
        tone = np.full((100, 160, 3), 235, np.uint8)
        tone[::4, ::4] = 90
        tone[1::4, 1::4] = 90
        page = np.concatenate([white, tint, tone], axis=1)
        mask = np.concatenate([_text_mask((100, 160))] * 3, axis=1)
        page[mask > 0] = 20
        smart_fill(page, mask, Config())
        report = smart_fill.last_report
        assert report["colour"] == report["heal"] == report["model"] == 7
        sent = smart_fill._fallback_model.masks[0]
        assert not sent[:, :320].any() and sent[:, 320:].any()


class TestMembrane:
    """The solver under the healing brush and the smooth fill."""

    def _disc(self, h, w, cy, cx, r):
        yy, xx = np.mgrid[:h, :w]
        return np.hypot(xx - cx, yy - cy) < r

    def test_a_slope_is_carried_straight_through(self):
        yy, xx = np.mgrid[:60, :80]
        truth = (0.5 * xx + 0.3 * yy + 20)[..., None].astype(np.float32)
        hole = self._disc(60, 80, 30, 40, 20)
        solved = paint.solve_membrane(np.where(hole[..., None], 0, truth), ~hole, hole)
        assert np.abs(solved - truth).max() < 0.5

    def test_it_agrees_with_a_fully_relaxed_solve(self):
        yy, xx = np.mgrid[:72, :96]
        hole = self._disc(72, 96, 36, 45, 28)
        start = ((np.sin(xx * 0.21) * 0.3 + np.cos(yy * 0.13) * 0.2 + 0.5) * 255)[..., None].astype(np.float32)
        fast = paint.solve_membrane(start, ~hole, hole)
        reference = start.copy()
        reference[hole] = 0
        for _ in range(20000):
            p = np.pad(reference, ((1, 1), (1, 1), (0, 0)), mode="edge")
            mean = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]) / 4
            reference[hole] = mean[hole]
        assert np.abs(fast - reference).max() < 1.0
        assert np.array_equal(fast[~hole], start[~hole])     # known pixels untouched

    def test_pixels_in_neither_mask_are_no_boundary(self):
        """A hole whose known rim is 200 on one side and nothing on the other
        fills at 200: what takes no part must not pull it towards its value."""
        values = np.zeros((30, 40, 1), np.float32)
        known = np.zeros((30, 40), bool)
        hole = np.zeros((30, 40), bool)
        hole[5:25, 10:30] = True
        known[5:25, 9] = True
        values[known] = 200
        solved = paint.solve_membrane(values, known, hole)
        assert np.abs(solved[hole] - 200).max() < 0.5
        assert (solved[~hole & ~known] == 0).all()

    def test_a_wide_hole_is_settled(self):
        """Plain relaxation moved one pixel a sweep, so the middle of a wide
        region kept its blurred first guess."""
        yy, xx = np.mgrid[:240, :240]
        clean = (40 + xx * 0.5 + yy * 0.25)[..., None].repeat(3, axis=2)
        image = clean.astype(np.uint8)
        region = np.zeros((240, 240), bool)
        region[20:220, 20:220] = True
        image[region] = 0
        filled = paint.smooth_fill(image, region)
        assert np.abs(filled.astype(int) - clean.astype(int))[region].max() <= 2
