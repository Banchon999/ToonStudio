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

from .base import InpaintModel
from .mask_fitting import pick_best_mask
from .schema import Config

logger = logging.getLogger(__name__)


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
    3. **Model** — the surroundings have texture: the region is left for LaMa.

    `last_report` says how many regions each took, so a caller can tell the
    user what was done.
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
        self.last_report = {clean_triage.COLOUR: 0, clean_triage.HEAL: 0, clean_triage.MODEL: 0}

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
        report = {clean_triage.COLOUR: 0, clean_triage.HEAL: 0, clean_triage.MODEL: 0}
        self.last_report = report
        binary_mask = np.where(mask > 127, 255, 0).astype(np.uint8)
        if not binary_mask.any():
            return result

        num_labels, labels = imk.connected_components(binary_mask)
        residual_mask = np.zeros_like(binary_mask)
        height, width = binary_mask.shape[:2]
        max_region_area = int(height * width * self.MAX_REGION_AREA_RATIO)

        for label in range(1, num_labels):
            component = labels == label
            area = int(component.sum())
            if area == 0:
                continue
            method = clean_triage.MODEL
            if area <= max_region_area:
                method = self._fill_component(result, component)
            if method == clean_triage.MODEL:
                residual_mask[component] = 255
            report[method] += 1

        logger.info(
            "Smart Fill: %d regions painted white, %d healed, %d sent to the model",
            report[clean_triage.COLOUR], report[clean_triage.HEAL], report[clean_triage.MODEL],
        )

        if residual_mask.any():
            result = self._get_fallback_model()(result, residual_mask, config)
        return result

    def _fill_component(self, result: np.ndarray, component: np.ndarray) -> str:
        """Clean one mask region in place if no model is needed; returns the
        method that suits it (clean_triage.COLOUR, HEAL or MODEL)."""
        conf = self.masker_conf
        ys, xs = np.nonzero(component)
        margin = (
            conf.min_mask_thickness
            + conf.mask_growth_step_pixels * conf.mask_growth_steps
            + 2
        )
        height, width = component.shape[:2]
        y1 = max(0, ys.min() - margin); y2 = min(height, ys.max() + 1 + margin)
        x1 = max(0, xs.min() - margin); x2 = min(width, xs.max() + 1 + margin)

        image_crop = result[y1:y2, x1:x2]
        mask_crop = np.where(component[y1:y2, x1:x2], 255, 0).astype(np.uint8)

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
        if min(int(ys.max() - ys.min()), int(xs.max() - xs.min())) + 1 > self.MAX_HEAL_THICKNESS:
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
