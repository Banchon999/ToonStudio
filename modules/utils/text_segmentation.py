"""Choosing how the precise text mask for a page gets made.

Two ways exist. The fast one thresholds each detected box on its own; the
precise one runs a text segmentation network over the whole page first and
uses its prediction to referee the thresholding. This module is the single
place that answers "which one, and on what device", so call sites do not each
have to reach into settings for it.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def model_segmentation_enabled(settings) -> bool:
    if settings is None:
        return False
    getter = getattr(settings, "get_use_text_segmentation_model", None)
    if getter is None:
        return False
    try:
        return bool(getter())
    except Exception:
        return False


#: The default: comic-text-detector's seg head over the whole page (text_seg_onnx).
WHOLE_PAGE = "ctd"
#: comic-text-mask, one detected box at a time (text_mask_onnx).
PER_BOX = "ctm"


def segmentation_engine(settings) -> str:
    """Which model makes the prediction: WHOLE_PAGE (default) or PER_BOX."""
    getter = getattr(settings, "get_text_segmentation_engine", None)
    try:
        value = getter() if getter is not None else WHOLE_PAGE
    except Exception:
        value = WHOLE_PAGE
    return PER_BOX if value == PER_BOX else WHOLE_PAGE


def _boxes(blocks) -> list:
    boxes = []
    for blk in blocks or ():
        box = getattr(blk, "xyxy", None)
        if box is not None and len(box) >= 4:
            boxes.append(box)
    return boxes


def segment_page(image: np.ndarray, settings, blocks=None) -> np.ndarray | None:
    """The page's text-probability map, or None to fall back to thresholding.

    ``blocks`` are the page's detected blocks in ``image``'s coordinates. The
    per-box model needs them; without them it answers with the whole-page model,
    so a caller that has none still gets a prediction.

    Returns None rather than raising when the model is off, unavailable or
    fails: cleaning with a slightly worse mask beats not cleaning at all.
    """
    if image is None or not model_segmentation_enabled(settings):
        return None

    try:
        from modules.utils.device import resolve_device

        device = resolve_device(settings.is_gpu_enabled(), backend="onnx")
        boxes = _boxes(blocks)
        if segmentation_engine(settings) == PER_BOX and boxes:
            try:
                from modules.detection.text_mask_onnx import get_masker

                return get_masker(device).page_map(image, boxes)
            except Exception:
                logger.exception("comic-text-mask unavailable; using the whole-page model")
        from modules.detection.text_seg_onnx import get_segmenter

        return get_segmenter(device).segment_cached(image)
    except Exception:
        logger.exception("Text segmentation model unavailable; falling back to thresholding")
        return None


def peek_page_mask(image: np.ndarray, settings) -> np.ndarray | None:
    """The page's prediction if it has already been computed, else None.

    For interactive code paths. Running the model takes seconds, which is fine
    inside a batch job and not fine between a brush stroke and its result — so
    the editor takes the better mask when cleaning has already produced one and
    thresholds otherwise, rather than freezing.
    """
    if image is None or not model_segmentation_enabled(settings):
        return None
    try:
        if segmentation_engine(settings) == PER_BOX:
            from modules.detection.text_mask_onnx import peek_masker

            found = peek_masker(image)
            if found is not None:
                return found
        from modules.detection.text_seg_onnx import peek_cached_mask

        return peek_cached_mask(image)
    except Exception:
        return None
