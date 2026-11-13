"""Run an ONNX model on OpenVINO's CPU plugin, falling back to ONNX Runtime.

ONNX Runtime's CPU kernels are slow on the convolutional networks this app
runs, and OpenVINO's CPU plugin runs the same ``.onnx`` file faster with the
same numbers: measured on a 4-core CPU, the AOT inpainter at 960x640 took
1.71 s on ONNX Runtime and 0.94 s here, LaMa at 768x512 2.64 s and 2.12 s,
both with the output equal to ONNX Runtime's to the last grey level. The text
segmentation model (`modules/detection/text_seg_onnx.py`) gains far more, from
its ConvTranspose layers.

**Precision is pinned to f32** (`CPU_CONFIG`). Left to itself, OpenVINO runs
in bf16 on a CPU that has it (AMX or AVX-512 BF16: recent Intel server and
workstation parts), which made AOT another 3x faster and moved inpainted
pixels by up to 62 grey levels — a different, unreviewed result on some
machines only. Speed that changes the picture is not taken silently.

`OpenVINOSession` answers the two calls the inpainters make of an
``onnxruntime.InferenceSession`` (``get_inputs()[i].name`` and
``run(None, feeds)``), so a model class swaps backends without other changes.
`make_cpu_session` decides which to give: OpenVINO when it is installed and
the device is the CPU, ONNX Runtime otherwise, when OpenVINO cannot load the
model, or when ``CT_ORT_ONLY=1`` is set. If OpenVINO fails during a call, the
session switches to ONNX Runtime for good and answers that call there.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

import numpy as np

logger = logging.getLogger(__name__)

#: Compile options for every model run here. See the module docstring.
CPU_CONFIG = {"PERFORMANCE_HINT": "LATENCY", "INFERENCE_PRECISION_HINT": "f32"}

#: ONNX Runtime devices that are real accelerators; anything else (``cpu``,
#: ``openvino``) is better served by OpenVINO's CPU plugin.
ORT_ACCELERATORS = {"cuda", "tensorrt", "rocm", "coreml"}


def wants_openvino(device: str | None) -> bool:
    if os.environ.get("CT_ORT_ONLY", "").strip() == "1":
        return False
    return str(device or "cpu").lower() not in ORT_ACCELERATORS


def compile_cpu(model_path: str):
    """The model compiled for OpenVINO's CPU plugin, in f32.

    Raises ImportError when openvino is not installed.
    """
    import openvino as ov  # optional dependency

    return ov.Core().compile_model(model_path, "CPU", CPU_CONFIG)


class _Input:
    def __init__(self, name: str):
        self.name = name


class OpenVINOSession:
    """An ``InferenceSession``-shaped wrapper over a compiled OpenVINO model."""

    backend = "openvino"

    def __init__(self, model_path: str):
        self.compiled = compile_cpu(model_path)
        self._inputs = [_Input(port.get_any_name()) for port in self.compiled.inputs]
        # One request, used under a lock: inpainting runs on worker threads
        # and an infer request must not be shared concurrently.
        self.request = self.compiled.create_infer_request()
        self._lock = threading.Lock()

    def get_inputs(self) -> list[_Input]:
        return list(self._inputs)

    def run(self, output_names, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        with self._lock:
            result = self.request.infer({name: np.ascontiguousarray(value) for name, value in feeds.items()})
            ports = self.compiled.outputs
            if output_names is not None:
                ports = [self.compiled.output(name) for name in output_names]
            return [np.array(result[port], copy=True) for port in ports]


class FallbackSession:
    """OpenVINO first; ONNX Runtime from the first failure on."""

    def __init__(self, primary: OpenVINOSession, make_fallback: Callable[[], Any], label: str):
        self._session = primary
        self._make_fallback = make_fallback
        self._label = label
        self._lock = threading.Lock()

    @property
    def backend(self) -> str:
        return getattr(self._session, "backend", "onnxruntime")

    def get_inputs(self):
        return self._session.get_inputs()

    def run(self, output_names, feeds):
        session = self._session
        try:
            return session.run(output_names, feeds)
        except Exception:
            if getattr(session, "backend", None) != "openvino":
                raise
            # Never let the faster path cost a page: switch for the rest of
            # the session and redo this call on ONNX Runtime.
            logger.exception("%s: OpenVINO inference failed; switching to ONNX Runtime", self._label)
            with self._lock:
                if self._session is session:
                    self._session = self._make_fallback()
            return self._session.run(output_names, feeds)


def make_cpu_session(model_path: str, device: str | None, make_ort: Callable[[], Any], label: str):
    """A session for `model_path`: OpenVINO on the CPU when it can, else `make_ort()`."""
    if wants_openvino(device):
        try:
            session = FallbackSession(OpenVINOSession(model_path), make_ort, label)
            logger.info("%s: OpenVINO CPU (f32)", label)
            return session
        except ImportError:
            logger.info("%s: openvino not installed; using ONNX Runtime", label)
        except Exception:
            logger.exception("%s: OpenVINO failed to load the model; using ONNX Runtime", label)
    logger.info("%s: ONNX Runtime (%s)", label, device)
    return make_ort()
