"""Smart Fill: paint what is white, heal what is smooth, inpaint the rest.

Uses the mask-fitting algorithm ported from PanelCleaner; see
`mask_fitting.py` for attribution. Distributed under GPL-3.0-or-later.
"""

import logging
from dataclasses import dataclass

import numpy as np
import imkit as imk

from core import clean_triage
from core.balloons import MIN_LIGHT
from core.paint import smooth_fill
from core.spot_heal import spot_heal

from .base import InpaintModel
from .mask_fitting import pick_best_mask
from .schema import Config

logger = logging.getLogger(__name__)

#: `Config.smart_fill_textured` values: what a region with texture around it gets.
TEXTURED_MODEL = "model"
TEXTURED_HEAL = "heal"
TEXTURED_LEAVE = "leave"
TEXTURED_MODES = (TEXTURED_MODEL, TEXTURED_HEAL, TEXTURED_LEAVE)
#: `last_report` key for regions left untouched.
LEFT = "left"


@dataclass
class MaskerConfig:
    """Tuning for mask fitting. Defaults match PanelCleaner's masker."""

    mask_growth_step_pixels: int = 2
    mask_growth_steps: int = 11
    min_mask_thickness: int = 4
    allow_colored_masks: bool = True
    off_white_max_threshold: int = 240
    mask_max_standard_deviation: float = 15.0
    mask_improvement_threshold: float = 0.1
    mask_selection_fast: bool = False


class SmartFill(InpaintModel):
    """Cleans each region of the mask with the cheapest tool that suits it.

    Every connected region is judged by what surrounds it, in this order:

    1. **White** — PanelCleaner's mask fitting finds a grown mask whose border
       is one colour, and that colour is white: the region is painted in it.
       This comes first and decides most speech bubbles.
    2. **Heal** — the surroundings are smooth but not one white (a gradient, a
       tinted caption box, a flat panel): the region is filled from the pixels
       just outside it, as the healing brush does, with no model.
    3. **Textured** — the surroundings have texture. What happens then is
       `Config.smart_fill_textured`, the user's choice of speed over quality:
       ``"model"`` (default) sends the region to LaMa; ``"heal"`` fills it
       with the spot healing brush (`core.spot_heal`): texture copied from
       the best-matching place nearby that is not lettering, in the tone of
       the region's own surroundings — no model, a fraction of the time; ``"leave"`` does not touch it, so the lettering stays for the
       user to fix by hand (what PanelCleaner does without inpainting).

    `last_report` says how many regions each took (``"left"`` for the
    untouched ones), so a caller can tell the user what was done.
    """

    name = "smart_fill"

    # Skip huge regions (full-page masks); a local fill only makes sense locally.
    MAX_REGION_AREA_RATIO = 0.5
    # A region wider than this many pixels on its short side is not healed: a
    # smooth fill across so much is a blur, however smooth its rim.
    MAX_HEAL_THICKNESS = 120

    def init_model(self, device, **kwargs):
        self.backend = kwargs.get("backend", "onnx")
        self._fill_device = device
        self._fallback_model = None
        self.masker_conf = kwargs.get("masker_conf") or MaskerConfig()
        self.last_report = self._empty_report()

    @staticmethod
    def _empty_report() -> dict:
        return {clean_triage.COLOUR: 0, clean_triage.HEAL: 0, clean_triage.MODEL: 0, LEFT: 0}

    @staticmethod
    def is_downloaded() -> bool:
        return True

    def forward(self, image, mask, config: Config):
        # Not used: __call__ is overridden and never pads/forwards.
        raise NotImplementedError

    def __call__(self, image: np.ndarray, mask: np.ndarray, config: Config):
        """
        image: [H, W, C] RGB, uint8
        mask: [H, W] with 255 marking regions to clean
        return: RGB image
        """
        result = image.copy()
        report = self._empty_report()
        self.last_report = report
        textured = getattr(config, "smart_fill_textured", TEXTURED_MODEL)
        if textured not in TEXTURED_MODES:
            textured = TEXTURED_MODEL
        binary_mask = np.where(mask > 127, 255, 0).astype(np.uint8)
        if not binary_mask.any():
            return result

        # Every region is worked on inside its own padded box: comparing and
        # scanning the whole page once per region (a letter, often 100+ on a
        # page) cost more than judging them did.
        num_labels, labels, stats, _centroids = imk.connected_components_with_stats(binary_mask)
        residual_mask = np.zeros_like(binary_mask)
        # Textured regions healed without the model: done together at the end,
        # each from texture found nearby that is not itself lettering.
        spot_mask = np.zeros(binary_mask.shape, bool)
        height, width = binary_mask.shape[:2]
        max_region_area = int(height * width * self.MAX_REGION_AREA_RATIO)

        for label in range(1, num_labels):
            area = int(stats[label, imk.CC_STAT_AREA])
            if area == 0:
                continue
            bounds = self._crop_bounds(stats[label], (height, width))
            y1, y2, x1, x2 = bounds
            component = labels[y1:y2, x1:x2] == label
            method = clean_triage.MODEL
            if area <= max_region_area:
                method = self._fill_component(result, component, bounds, stats[label])
            if method == clean_triage.MODEL:
                if textured == TEXTURED_HEAL:
                    self._grow_for_heal(spot_mask, component, bounds)
                    method = clean_triage.HEAL
                elif textured == TEXTURED_LEAVE:
                    method = LEFT
                else:
                    residual_mask[y1:y2, x1:x2][component] = 255
            report[method] += 1

        logger.info(
            "Smart Fill: %d regions painted white, %d healed, %d sent to the model, %d left as they are",
            report[clean_triage.COLOUR], report[clean_triage.HEAL], report[clean_triage.MODEL], report[LEFT],
        )

        if spot_mask.any():
            result = spot_heal(result, spot_mask, avoid=binary_mask > 0)
        if residual_mask.any():
            result = self._get_fallback_model()(result, residual_mask, config)
        return result

    def _crop_bounds(self, stat, shape) -> tuple[int, int, int, int]:
        """(y1, y2, x1, x2): a component's box (from its connected-component
        `stat`) plus room for the grown masks, within an image of `shape`."""
        conf = self.masker_conf
        margin = (
            conf.min_mask_thickness
            + conf.mask_growth_step_pixels * conf.mask_growth_steps
            + 2
        )
        height, width = shape
        left, top = int(stat[imk.CC_STAT_LEFT]), int(stat[imk.CC_STAT_TOP])
        right = left + int(stat[imk.CC_STAT_WIDTH])
        bottom = top + int(stat[imk.CC_STAT_HEIGHT])
        return max(0, top - margin), min(height, bottom + margin), max(0, left - margin), min(width, right + margin)

    def _grow_for_heal(self, spot_mask: np.ndarray, component: np.ndarray, bounds) -> None:
        """Mark a textured region for spot healing (`core.spot_heal`).

        `component` is the region inside `bounds` (y1, y2, x1, x2). It is grown
        past the glyphs' anti-aliased rim first, as the heal branch of
        `_fill_component` does when mask fitting found nothing, so no dark
        fringe is carried into the fill."""
        y1, y2, x1, x2 = bounds
        grown = imk.dilate(component.astype(np.uint8), np.ones((3, 3), np.uint8),
                           iterations=max(1, self.masker_conf.min_mask_thickness // 2)) > 0
        spot_mask[y1:y2, x1:x2] |= grown

    def _fill_component(self, result: np.ndarray, component: np.ndarray, bounds, stat) -> str:
        """Clean one mask region in place if no model is needed; returns the
        method that suits it (clean_triage.COLOUR, HEAL or MODEL).

        `component` is the region inside `bounds` (y1, y2, x1, x2) and `stat`
        its connected-component statistics."""
        conf = self.masker_conf
        y1, y2, x1, x2 = bounds

        image_crop = result[y1:y2, x1:x2]
        mask_crop = np.where(component, 255, 0).astype(np.uint8)

        # The filled bounding box is offered alongside the grown masks: masks
        # derived from connected components are ragged, so on a flat bubble the
        # solid box often has a more uniform border and fills more cleanly.
        best_mask, best_color, _deviation = pick_best_mask(
            image_crop,
            mask_crop,
            self._bounding_box_mask(mask_crop, conf.min_mask_thickness),
            conf,
        )
        # 1. White first: one flat, white surround is painted in its colour.
        if best_mask is not None and best_color is not None and min(best_color) >= MIN_LIGHT:
            image_crop[best_mask > 0] = np.array(best_color, dtype=np.uint8)
            return clean_triage.COLOUR

        # 2. Smooth but not white: healed from the pixels around it. The mask
        # fitting's choice is used when it made one (it has cleared any glow);
        # otherwise the region grown past the glyphs' anti-aliased rim.
        if best_mask is not None:
            region = best_mask > 0
        else:
            region = imk.dilate(mask_crop, np.ones((3, 3), np.uint8),
                                iterations=max(1, conf.min_mask_thickness // 2)) > 0
        if min(int(stat[imk.CC_STAT_WIDTH]), int(stat[imk.CC_STAT_HEIGHT])) > self.MAX_HEAL_THICKNESS:
            return clean_triage.MODEL
        method, _colour, _texture = clean_triage.triage(image_crop, clean_triage.ring_of(region, 3))
        if method == clean_triage.MODEL:
            return clean_triage.MODEL
        # A white ring found here (the mask fitting saw too much spread over
        # its wider border) heals just as well: on white the two agree.
        image_crop[...] = smooth_fill(image_crop, region)
        return clean_triage.HEAL

    @staticmethod
    def _bounding_box_mask(mask_crop: np.ndarray, pad: int) -> np.ndarray:
        """A solid rectangle covering the component, padded so it clears glyph
        antialiasing."""
        height, width = mask_crop.shape[:2]
        ys, xs = np.nonzero(mask_crop)
        box = np.zeros_like(mask_crop)
        y1 = max(0, ys.min() - pad); y2 = min(height, ys.max() + 1 + pad)
        x1 = max(0, xs.min() - pad); x2 = min(width, xs.max() + 1 + pad)
        box[y1:y2, x1:x2] = 255
        return box

    def _get_fallback_model(self):
        if self._fallback_model is None:
            from .lama import LaMa
            logger.info("Smart Fill: loading LaMa for the textured regions")
            self._fallback_model = LaMa(self._fill_device, backend=self.backend)
        return self._fallback_model
