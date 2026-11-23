"""comic-text-mask: a per-crop lettering mask, the other choice of text segmentation model.

`TareHimself/comic-text-mask` (MIT, a UNet with a ResNet-18 encoder, 14.3M parameters,
by TareHimself for comic-localizer) reads one detected text region at a time,
letterboxed into 384×384, and returns a text probability per pixel. Its weights are
published as TorchScript, which the app cannot run, so they are exported once to ONNX
(``uint8`` RGB in, probability out — the normalisation and the sigmoid are inside the
graph; the export matched TorchScript within 1e-5) and published as
``DeWoke/comic-text-mask-onnx`` with the MIT notice.

It answers the same question as the default model (``text_seg_onnx``, comic-text-detector's
``seg`` head over the whole page) and is used the same way: its probabilities, pasted into
a page-sized map, referee the thresholding in ``generate_mask``. Unlike the default it needs
the detected boxes, so ``text_segmentation.segment_page`` passes them; a call without boxes
falls back to the default model. Measured (2026-11): on the three Korean test pages it
removed one invitation line the default left, on three Japanese manga pages one stray kana,
otherwise the same; ~60 ms a block and ~150 MB, against ~1.5 s a page and ~420 MB.
"""
from __future__ import annotations

import logging
import threading

import numpy as np
from PIL import Image

from modules.utils.download import ModelDownloader, ModelID

logger = logging.getLogger(__name__)

INPUT_SIZE = 384
CROP_SHARE = 0.15  # room round each box, as a share of its size: lettering overhangs boxes
CROP_LEAST = 8     # ...and never less than this many pixels


def crop_bounds(box, shape) -> tuple[int, int, int, int]:
    """The region read for one detected box, padded and clipped to the page."""
    x1, y1, x2, y2 = (int(round(float(v))) for v in box[:4])
    px = max(CROP_LEAST, int((x2 - x1) * CROP_SHARE))
    py = max(CROP_LEAST, int((y2 - y1) * CROP_SHARE))
    height, width = shape[:2]
    return max(0, x1 - px), max(0, y1 - py), min(width, x2 + px), min(height, y2 + py)


def letterbox(crop: np.ndarray, size: int = INPUT_SIZE) -> tuple[np.ndarray, int, int]:
    """The crop scaled to fit ``size`` at the top left of a black square, as it was trained."""
    h, w = crop.shape[:2]
    scale = size / max(h, w)
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    square = np.zeros((size, size, 3), np.uint8)
    square[:nh, :nw] = np.asarray(Image.fromarray(crop).resize((nw, nh), Image.Resampling.BILINEAR))
    return square, nh, nw


def _box_key(box) -> tuple[int, int, int, int]:
    return tuple(int(round(float(v))) for v in box[:4])


class ComicTextMasker:
    """One ONNX session; remembers the crops it read for the latest page."""

    def __init__(self):
        self.session = None
        self._device = None
        self._lock = threading.Lock()
        self._page_key = None
        self._crops: dict[tuple, tuple[tuple[int, int, int, int], np.ndarray]] = {}

    def initialize(self, device: str = "cpu") -> None:
        if self.session is not None and device == self._device:
            return
        from modules.utils.device import get_providers
        from modules.utils.onnx import make_session

        ModelDownloader.get(ModelID.COMIC_TEXT_MASK_ONNX)
        path = ModelDownloader.primary_path(ModelID.COMIC_TEXT_MASK_ONNX)
        self.session = make_session(path, providers=get_providers(device))
        self._device = device

    def predict_crop(self, crop: np.ndarray) -> np.ndarray:
        """Probability (uint8 0-255) for every pixel of one crop."""
        if crop.ndim == 2:
            crop = np.repeat(crop[..., None], 3, axis=2)
        crop = np.ascontiguousarray(crop[..., :3])
        square, nh, nw = letterbox(crop)
        prob = self.session.run(None, {self.session.get_inputs()[0].name: square.transpose(2, 0, 1)[None]})[0]
        prob = (np.clip(prob[0, 0, :nh, :nw], 0.0, 1.0) * 255.0).astype(np.uint8)
        h, w = crop.shape[:2]
        return np.asarray(Image.fromarray(prob).resize((w, h), Image.Resampling.BILINEAR))

    @staticmethod
    def _page_key_of(image: np.ndarray) -> tuple:
        from modules.detection.text_seg_onnx import _quick_hash

        return (image.shape, int(image.dtype.num), _quick_hash(image))

    def page_map(self, image: np.ndarray, boxes) -> np.ndarray:
        """A page-sized probability map from every box read on this page so far.

        Callers ask with different subsets of a page's boxes (the whole page, then one
        block whose fast fill failed), so each box is read once and remembered until the
        page changes, and the map holds every box remembered — a neighbour reaching into
        a block's crop is in it as the default model's whole-page map would have it.
        """
        key = self._page_key_of(image)
        with self._lock:
            if key != self._page_key:
                self._page_key, self._crops = key, {}
            todo = [b for b in boxes if _box_key(b) not in self._crops]
        for box in todo:
            x1, y1, x2, y2 = crop_bounds(box, image.shape)
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            prob = self.predict_crop(image[y1:y2, x1:x2])
            with self._lock:
                if self._page_key == key:
                    self._crops[_box_key(box)] = ((x1, y1, x2, y2), prob)
        return self.peek(image)

    def peek(self, image: np.ndarray) -> np.ndarray | None:
        """The map from crops already read for this page, without reading any."""
        key = self._page_key_of(image)
        with self._lock:
            if key != self._page_key or not self._crops:
                return None
            crops = list(self._crops.values())
        page = np.zeros(image.shape[:2], np.uint8)
        for (x1, y1, x2, y2), prob in crops:
            np.maximum(page[y1:y2, x1:x2], prob, out=page[y1:y2, x1:x2])
        return page


_masker: ComicTextMasker | None = None
_masker_lock = threading.Lock()


def get_masker(device: str = "cpu") -> ComicTextMasker:
    global _masker
    with _masker_lock:
        if _masker is None:
            _masker = ComicTextMasker()
        masker = _masker
    masker.initialize(device)
    return masker


def release_masker() -> bool:
    """Drop the session and remembered crops; True when one was loaded."""
    global _masker
    with _masker_lock:
        had = _masker is not None
        _masker = None
    return had


def peek_masker(image: np.ndarray) -> np.ndarray | None:
    with _masker_lock:
        masker = _masker
    return masker.peek(image) if masker is not None else None
