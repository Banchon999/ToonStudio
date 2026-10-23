"""Pixel-level text segmentation with comic-text-detector.

Detection gives boxes; cleaning needs to know which *pixels* inside a box are
glyph. Thresholding a crop guesses at that from the crop alone, which fails
whenever the text is not simply the darkest or lightest thing in the box —
over gradients, over screentone, on coloured or outlined lettering.

This runs the segmentation head of comic-text-detector
(https://github.com/dmMaze/comic-text-detector, GPL-3.0), the same network
PanelCleaner uses, over the whole page once and returns its text-probability
map. `modules.inpainting.text_mask_refine` then uses that map as the referee
for a per-box binarisation.

Only the model's `seg` output is used. Its box and text-line outputs are
ignored: this project has its own detector, and feeding those boxes into the
refinement is strictly better than feeding the ones this network found.

**It runs on OpenVINO's CPU plugin when the ``openvino`` package is present.**
ONNX Runtime's CPU kernel for ``ConvTranspose`` is pathologically slow on this
network: 37-40 s per call on a 4-core CPU (ConvTranspose alone ~28 s of it),
for a model of 191 GFLOP. OpenVINO's CPU plugin runs the same file in ~0.5 s
with a mask identical pixel for pixel. That matters most in webtoon mode, which
segments every ~2400 px chunk of a strip separately: a 20 000 px strip used to
spend five minutes here. Any OpenVINO failure, at load or at run time, falls
back to ONNX Runtime for good, and ``CT_TEXT_SEG_BACKEND=onnxruntime`` forces
the old path. A GPU the user enabled (CUDA, TensorRT, ...) still goes through
ONNX Runtime, where ConvTranspose is fast.

**A page taller than twice its width is also read in windows** (`tile_rows`).
The network sees a fixed 1024x1024 input, so a whole 800x5000 webtoon page went
in at a fifth of its size and came back blurred: Clean left the first and last
letters of each line of a red caption over a dark panel, and lettering cut by
the page's edge was never touched. Windows 1.5 page-widths tall, the
proportions of the pages the network was trained on, overlap by a fifth (more
than a line of text, so every line lies whole inside one window) and are added
to the whole-page pass, the higher probability winning. Anything up to twice
as tall as it is wide still goes in whole, unchanged.
"""

from __future__ import annotations

import logging
import os
import threading

import numpy as np
from PIL import Image

from modules.utils.device import get_providers
from modules.utils.download import ModelDownloader, ModelID
from modules.utils.onnx import make_session

INPUT_SIZE = 1024

#: Pages taller than this many widths are segmented in windows...
TILE_MIN_ASPECT = 2.0
#: ...each this many widths tall (a page's proportions, so the lettering is
#: shrunk no more than on an ordinary page)...
TILE_ASPECT = 1.5
#: ...overlapping their neighbours by this fraction of a window.
TILE_OVERLAP = 0.2
#: On ONNX Runtime's CPU kernels a call costs ~40 s rather than ~0.5 s (see
#: above), so windows there are twice as tall: three for an 800x5000 page
#: instead of five, and a 2400 px webtoon chunk stays one call.
SLOW_TILE_ASPECT = 3.0

logger = logging.getLogger(__name__)

#: ONNX Runtime devices that are real accelerators; anything else (``cpu``,
#: ``openvino``) is better served by OpenVINO's CPU plugin.
_ORT_ACCELERATORS = {"cuda", "tensorrt", "rocm", "coreml"}


def _wants_openvino(device: str) -> bool:
    if os.environ.get("CT_TEXT_SEG_BACKEND", "").strip().lower() == "onnxruntime":
        return False
    return str(device or "cpu").lower() not in _ORT_ACCELERATORS


class _OrtRunner:
    backend = "onnxruntime"

    def __init__(self, file_path: str, device: str):
        self.session = make_session(file_path, providers=get_providers(device))
        self.input_name = self.session.get_inputs()[0].name

    def run(self, tensor: np.ndarray) -> np.ndarray:
        return self.session.run(['seg'], {self.input_name: tensor})[0]


class _OpenVINORunner:
    """The same ONNX file, compiled by OpenVINO for the CPU."""

    backend = "openvino"

    def __init__(self, file_path: str):
        import openvino as ov  # optional dependency: ImportError means "not here"

        self.compiled = ov.Core().compile_model(file_path, "CPU")
        self.input = self.compiled.input(0)
        self.output = self.compiled.output("seg")
        # One request, used under a lock: segmentation is called from worker
        # threads and an infer request is not safe to share concurrently.
        self.request = self.compiled.create_infer_request()
        self._lock = threading.Lock()

    def run(self, tensor: np.ndarray) -> np.ndarray:
        with self._lock:
            result = self.request.infer({self.input: tensor})
            return np.array(result[self.output], copy=True)


class ComicTextSegmenter:
    """Runs the segmentation head and caches the last page's result.

    Detection, cleaning and rendering all reach for the same page's mask, so
    the last result is kept — the model costs a second or two per page on CPU
    and recomputing it three times over is the whole cost again, twice.
    """

    def __init__(self):
        self.session = None  # the runner: _OpenVINORunner or _OrtRunner
        self._device = None
        self._file_path = None
        self._lock = threading.Lock()
        self._cache_key = None
        self._cache_value = None

    def initialize(self, device: str = 'cpu') -> None:
        with self._lock:
            if self.session is not None and self._device == device:
                return
            file_path = ModelDownloader.get_file_path(
                ModelID.COMIC_TEXT_SEG_ONNX, 'comic-text-detector.onnx'
            )
            self.session = self._make_runner(file_path, device)
            self._file_path = file_path
            self._device = device
            self._cache_key = None
            self._cache_value = None

    @staticmethod
    def _make_runner(file_path: str, device: str):
        if _wants_openvino(device):
            try:
                runner = _OpenVINORunner(file_path)
                logger.info("Text segmentation: OpenVINO CPU")
                return runner
            except ImportError:
                logger.info("Text segmentation: openvino not installed; using ONNX Runtime")
            except Exception:
                logger.exception("Text segmentation: OpenVINO failed to load the model; using ONNX Runtime")
        logger.info("Text segmentation: ONNX Runtime (%s)", device)
        return _OrtRunner(file_path, device)

    def _run(self, tensor: np.ndarray) -> np.ndarray:
        runner = self.session
        try:
            return runner.run(tensor)
        except Exception:
            if runner.backend != "openvino":
                raise
            # Never let the faster path cost a page: switch to ONNX Runtime
            # for the rest of the session and redo this call there.
            logger.exception("Text segmentation: OpenVINO inference failed; switching to ONNX Runtime")
            fallback = _OrtRunner(self._file_path, self._device or "cpu")
            with self._lock:
                self.session = fallback
            return fallback.run(tensor)

    @property
    def backend(self) -> str | None:
        return getattr(self.session, "backend", None)

    def _slow(self) -> bool:
        """ONNX Runtime on the CPU, where every call costs tens of seconds."""
        return self.backend == "onnxruntime" and str(self._device or "cpu").lower() not in _ORT_ACCELERATORS

    @staticmethod
    def _letterbox(image: np.ndarray) -> tuple[np.ndarray, int, int]:
        """Scale to fit 1024x1024 and pad the bottom and right with black.

        Padding only two sides, rather than centring, is what upstream does —
        it keeps the mapping back to page coordinates a plain division.
        """
        height, width = image.shape[:2]
        ratio = min(INPUT_SIZE / height, INPUT_SIZE / width)
        new_w = int(round(width * ratio))
        new_h = int(round(height * ratio))

        resized = np.asarray(
            Image.fromarray(image).resize((new_w, new_h), Image.Resampling.BILINEAR)
        )
        canvas = np.zeros((INPUT_SIZE, INPUT_SIZE, 3), dtype=np.uint8)
        canvas[:new_h, :new_w] = resized[..., :3]
        return canvas, INPUT_SIZE - new_w, INPUT_SIZE - new_h

    def segment(self, image: np.ndarray) -> np.ndarray:
        """Return a page-sized uint8 text-probability map (0-255)."""
        if self.session is None:
            raise RuntimeError("ComicTextSegmenter.initialize() must be called first")

        if image.ndim == 2:
            image = np.repeat(image[..., None], 3, axis=2)

        height, width = image.shape[:2]
        windows = tile_rows(height, width, SLOW_TILE_ASPECT if self._slow() else TILE_ASPECT)
        seg = self._segment_whole(image)
        if len(windows) == 1:
            return seg
        # The windows are added to the whole-page pass, not put in its place:
        # its broad, blurred prediction is what makes the mask refinement take
        # in the glow around white lettering in a bubble. With the sharp
        # windows alone, five glowing captions on real pages were cleaned to
        # readable grey ghosts of their words.
        seg = np.array(seg)
        for top, bottom in windows:
            band = seg[top:bottom]
            np.maximum(band, self._segment_whole(image[top:bottom]), out=band)
        return seg

    def _segment_whole(self, image: np.ndarray) -> np.ndarray:
        canvas, pad_w, pad_h = self._letterbox(image)

        # The network was trained on BGR-ordered arrays; this project carries
        # RGB everywhere, so the channels are reversed on the way in.
        tensor = canvas[..., ::-1].astype(np.float32) / 255.0
        tensor = np.ascontiguousarray(tensor.transpose(2, 0, 1)[np.newaxis, ...])

        seg = np.clip(self._run(tensor).squeeze() * 255.0, 0, 255).astype(np.uint8)

        # Drop the padding, then stretch back to the page.
        seg = seg[: INPUT_SIZE - pad_h, : INPUT_SIZE - pad_w]
        height, width = image.shape[:2]
        return np.asarray(
            Image.fromarray(seg).resize((width, height), Image.Resampling.BILINEAR)
        )

    @staticmethod
    def _key(image: np.ndarray) -> tuple:
        return (image.shape, int(image.dtype.num), _quick_hash(image))

    def peek(self, image: np.ndarray) -> np.ndarray | None:
        """The cached mask for this page, without computing one."""
        with self._lock:
            if self._cache_key is not None and self._key(image) == self._cache_key:
                return self._cache_value
        return None

    def segment_cached(self, image: np.ndarray) -> np.ndarray:
        key = self._key(image)
        with self._lock:
            if key == self._cache_key:
                return self._cache_value
        value = self.segment(image)
        with self._lock:
            self._cache_key = key
            self._cache_value = value
        return value


def tile_rows(height: int, width: int, aspect: float = TILE_ASPECT) -> list[tuple[int, int]]:
    """The row ranges a page is segmented in: the whole page, or overlapping
    windows `aspect` widths tall down a strip, the last one ending on the
    page's last row."""
    # A floor, so a strip a few dozen pixels wide is not cut into hundreds.
    window = max(int(round(aspect * width)), INPUT_SIZE // 2)
    if height <= TILE_MIN_ASPECT * width or height <= window:
        return [(0, height)]
    step = max(1, int(window * (1.0 - TILE_OVERLAP)))
    tops = list(range(0, height - window + 1, step))
    if tops[-1] + window < height:
        tops.append(height - window)
    return [(top, top + window) for top in tops]


def _quick_hash(image: np.ndarray) -> int:
    """Cheap content fingerprint.

    Hashing every byte of a webtoon strip costs more than it saves, so this
    samples a coarse grid — enough to tell two pages apart, and a collision
    only ever means a stale mask for one page.
    """
    sample = image[:: max(1, image.shape[0] // 64), :: max(1, image.shape[1] // 64)]
    return hash(np.ascontiguousarray(sample).tobytes())


_segmenter: ComicTextSegmenter | None = None
_segmenter_lock = threading.Lock()


def get_segmenter(device: str = 'cpu') -> ComicTextSegmenter:
    """The shared segmenter, downloading and loading the model on first use."""
    global _segmenter
    with _segmenter_lock:
        if _segmenter is None:
            _segmenter = ComicTextSegmenter()
    _segmenter.initialize(device)
    return _segmenter


def peek_cached_mask(image: np.ndarray) -> np.ndarray | None:
    """This page's mask if it is already in hand — never loads or runs a model."""
    with _segmenter_lock:
        segmenter = _segmenter
    return segmenter.peek(image) if segmenter is not None else None


#: A frozen build re-invokes itself with this flag to prove OpenVINO works
#: inside the bundle (see comic.py and the build workflows).
OPENVINO_SELF_TEST_FLAG = "--openvino-self-test"


def openvino_self_test() -> str | None:
    """None when OpenVINO can load ONNX and run a transposed convolution on
    the CPU, else the reason it cannot.

    PyInstaller can ship ``openvino`` without the plugins and frontends it
    loads by path at run time, and then the import succeeds and the first real
    call fails. This exercises exactly those pieces — the ONNX frontend that
    reads the model file and the CPU plugin that runs it — with a graph built
    in memory, so it needs no model download.
    """
    try:
        import openvino as ov
        from openvino import opset13 as ops
        from openvino.frontend import FrontEndManager
    except Exception as exc:
        return f"openvino import failed: {type(exc).__name__}: {exc}"
    try:
        if "onnx" not in FrontEndManager().get_available_front_ends():
            return "openvino's ONNX frontend is missing"
        core = ov.Core()
        if "CPU" not in core.available_devices:
            return "openvino's CPU plugin is missing"
        x = ops.parameter([1, 4, 8, 8], np.float32, name="x")
        w = ops.constant(np.ones((4, 2, 4, 4), np.float32))
        y = ops.convolution_backprop_data(x, w, strides=[2, 2], pads_begin=[1, 1],
                                          pads_end=[1, 1], dilations=[1, 1])
        compiled = core.compile_model(ov.Model([y], [x], "self_test"), "CPU")
        out = compiled({"x": np.ones((1, 4, 8, 8), np.float32)})[compiled.output(0)]
        if tuple(out.shape) != (1, 2, 16, 16) or not np.isfinite(out).all():
            return f"unexpected self-test output {tuple(out.shape)}"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None
