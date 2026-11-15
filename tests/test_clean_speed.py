"""Cleaning on the CPU, faster without changing the result.

Three changes, each pinned here:

* The AOT and LaMa inpainters run on OpenVINO's CPU plugin (when it is
  installed), in f32 — AOT went from 3.9 s to 2.8 s over a run of patch
  sizes, with no pixel more than one grey level from ONNX Runtime's. A failure
  falls back to ONNX Runtime, as the text segmentation model always has.
* The fast bubble fill's halo search builds every growth from one chain of
  single dilations instead of dilating from scratch per candidate (165
  dilations per bubble → 14), with identical masks.
* Smart Fill can be told what to do with lettering over texture: send it to
  LaMa (as before), heal it with no model, or leave it for the user. Asked for
  by the owner: white bubbles were already fast, and the model was the slow
  part.
"""

import types

import numpy as np
import pytest

from modules.inpainting.schema import Config
from modules.inpainting.smart_fill import SmartFill
from modules.utils import openvino_cpu


# --- OpenVINO sessions ---------------------------------------------------------

@pytest.fixture
def tiny_inpainter(tmp_path):
    """A two-input, dynamic-shape conv model shaped like AOT's inputs."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper

    rng = np.random.default_rng(0)
    w = numpy_helper.from_array((rng.standard_normal((3, 4, 3, 3)) * 0.3).astype(np.float32), "w")
    nodes = [
        helper.make_node("Concat", ["image", "mask"], ["x"], axis=1),
        helper.make_node("Conv", ["x", "w"], ["c"], pads=[1, 1, 1, 1]),
        helper.make_node("Tanh", ["c"], ["out"]),
    ]
    graph = helper.make_graph(
        nodes, "tiny_inpaint",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, [1, 3, "h", "w"]),
         helper.make_tensor_value_info("mask", TensorProto.FLOAT, [1, 1, "h", "w"])],
        [helper.make_tensor_value_info("out", TensorProto.FLOAT, [1, 3, "h", "w"])],
        initializer=[w],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    path = tmp_path / "tiny-inpaint.onnx"
    onnx.save(model, str(path))
    return str(path)


def _ort(path):
    from modules.utils.onnx import make_session
    return make_session(path, providers=["CPUExecutionProvider"])


def _feeds(session, h, w, seed=0):
    rng = np.random.default_rng(seed)
    names = [i.name for i in session.get_inputs()]
    return {names[0]: rng.uniform(-1, 1, (1, 3, h, w)).astype(np.float32),
            names[1]: (rng.random((1, 1, h, w)) > 0.7).astype(np.float32)}


class TestOpenVINOSession:
    def test_cpu_inpainting_uses_openvino_and_agrees_with_onnxruntime(self, tiny_inpainter, monkeypatch):
        pytest.importorskip("openvino")
        monkeypatch.delenv("CT_ORT_ONLY", raising=False)
        fast = openvino_cpu.make_cpu_session(tiny_inpainter, "cpu", lambda: _ort(tiny_inpainter), "test")
        slow = _ort(tiny_inpainter)
        assert fast.backend == "openvino"
        # Patches come in every size: one compiled model has to take them all.
        for h, w in [(64, 96), (128, 40), (64, 96)]:
            feeds = _feeds(slow, h, w)
            assert np.abs(fast.run(None, feeds)[0] - slow.run(None, feeds)[0]).max() < 1e-4

    def test_precision_is_pinned_to_f32(self, tiny_inpainter):
        """Left alone, OpenVINO picks bf16 on a CPU that has it — 62 grey
        levels off on AOT, and only on some machines."""
        pytest.importorskip("openvino")
        compiled = openvino_cpu.compile_cpu(tiny_inpainter)
        assert str(compiled.get_property("INFERENCE_PRECISION_HINT")) in {"f32", "<Type: 'float32'>"}

    def test_a_gpu_or_the_environment_variable_keeps_onnxruntime(self, tiny_inpainter, monkeypatch):
        made = []
        make = lambda: made.append(1) or _ort(tiny_inpainter)  # noqa: E731
        openvino_cpu.make_cpu_session(tiny_inpainter, "cuda", make, "test")
        monkeypatch.setenv("CT_ORT_ONLY", "1")
        openvino_cpu.make_cpu_session(tiny_inpainter, "cpu", make, "test")
        assert made == [1, 1]

    def test_missing_openvino_falls_back(self, tiny_inpainter, monkeypatch):
        def missing(*a, **k):
            raise ImportError("no openvino")
        monkeypatch.setattr(openvino_cpu, "compile_cpu", missing)
        monkeypatch.delenv("CT_ORT_ONLY", raising=False)
        session = openvino_cpu.make_cpu_session(tiny_inpainter, "cpu", lambda: _ort(tiny_inpainter), "test")
        assert not isinstance(session, openvino_cpu.FallbackSession)

    def test_an_inference_failure_switches_to_onnxruntime_and_still_answers(self, tiny_inpainter, monkeypatch):
        pytest.importorskip("openvino")
        monkeypatch.delenv("CT_ORT_ONLY", raising=False)
        session = openvino_cpu.make_cpu_session(tiny_inpainter, "cpu", lambda: _ort(tiny_inpainter), "test")
        assert session.backend == "openvino"

        def boom(self, *a, **k):
            raise RuntimeError("plugin crashed")
        monkeypatch.setattr(openvino_cpu.OpenVINOSession, "run", boom)
        reference = _ort(tiny_inpainter)
        feeds = _feeds(reference, 32, 48)
        out = session.run(None, feeds)[0]
        assert session.backend == "onnxruntime"
        assert np.array_equal(out, reference.run(None, feeds)[0])


# --- Halo search ---------------------------------------------------------------

def test_halo_search_gives_the_same_region_as_dilating_from_scratch():
    import imkit as imk
    from pipeline import inpainting
    from pipeline.inpainting import FAST_FILL_GROWTH_STEPS, InpaintingHandler

    rng = np.random.default_rng(4)
    crop = np.full((160, 240, 3), 245, np.uint8)
    yy, xx = np.mgrid[:160, :240]
    halo = np.hypot(yy - 80, xx - 120) < 50
    crop[halo] = 200  # a glow the search should grow past
    text = np.zeros((160, 240), bool)
    text[60:100, 80:160] = rng.random((40, 80)) > 0.7
    crop[text] = 20
    bubble = np.hypot((yy - 80) / 75, (xx - 120) / 115) < 1

    def from_scratch(crop, fill_region, bubble_mask, background=None):
        grow = np.ones((3, 3), np.uint8)
        fill_u8 = fill_region.astype(np.uint8)
        candidates = []
        for step in FAST_FILL_GROWTH_STEPS:
            inner = imk.dilate(fill_u8, grow, iterations=step) > 0
            ring = (imk.dilate(fill_u8, grow, iterations=step + 3) > 0) & ~inner
            inner &= bubble_mask
            ring &= bubble_mask
            on_background = True
            if background is not None and np.any(ring):
                median = np.median(crop[ring].reshape(-1, crop.shape[-1]), axis=0)
                on_background = float(np.max(np.abs(median - background))) <= inpainting.FAST_FILL_HALO_COLOUR
            candidates.append((inner, inpainting.plane_residual(crop, ring), on_background))
        usable = [c for c in candidates if c[2]] or candidates
        best = min(score for _i, score, _b in usable)
        for inner, score, _b in usable:
            if score <= best + inpainting.FAST_FILL_HALO_SLACK:
                return inner, score
        return usable[0][0], usable[0][1]

    for background in (None, np.array([245, 245, 245])):
        new_region, new_score = InpaintingHandler._grow_past_halo(crop, text, bubble, background)
        old_region, old_score = from_scratch(crop, text, bubble, background)
        assert np.array_equal(new_region, old_region)
        assert new_score == old_score


# --- Smart Fill: text over texture ---------------------------------------------

class _Model:
    """Stands in for LaMa and records whether it was asked."""

    def __init__(self):
        self.calls = 0

    def __call__(self, image, mask, config):
        self.calls += 1
        out = image.copy()
        out[mask > 0] = (1, 2, 3)
        return out


def _textured_page():
    page = np.full((100, 160, 3), 235, np.uint8)
    page[::4, ::4] = 90
    page[1::4, 1::4] = 90
    mask = np.zeros((100, 160), np.uint8)
    for x in range(40, 120, 12):
        mask[40:64, x:x + 5] = 255
    page[mask > 0] = 20
    return page, mask


@pytest.fixture
def fill():
    fill = SmartFill("cpu")
    fill._fallback_model = _Model()
    return fill


class TestSmartFillTextured:
    def test_the_default_still_sends_texture_to_the_model(self, fill):
        page, mask = _textured_page()
        assert Config().smart_fill_textured == "model"
        fill(page, mask, Config())
        assert fill._fallback_model.calls == 1
        assert fill.last_report["model"] == 7

    def test_heal_removes_the_text_without_the_model(self, fill):
        page, mask = _textured_page()
        cleaned = fill(page, mask, Config(smart_fill_textured="heal"))
        assert fill._fallback_model.calls == 0
        assert fill.last_report["heal"] == 7 and fill.last_report["model"] == 0
        # The dark glyphs are gone: what replaced them is in the tone's range.
        assert cleaned[mask > 0].min() > 60
        # Nothing far from the text moved.
        assert np.array_equal(cleaned[:, :20], page[:, :20])

    def test_leave_keeps_the_text_for_the_user(self, fill):
        page, mask = _textured_page()
        cleaned = fill(page, mask, Config(smart_fill_textured="leave"))
        assert fill._fallback_model.calls == 0
        assert fill.last_report["left"] == 7
        assert np.array_equal(cleaned, page)

    def test_heal_and_leave_never_load_lama(self, monkeypatch):
        fill = SmartFill("cpu")
        monkeypatch.setattr(fill, "_get_fallback_model", lambda: pytest.fail("LaMa was loaded"))
        page, mask = _textured_page()
        fill(page, mask, Config(smart_fill_textured="heal"))
        fill(page, mask, Config(smart_fill_textured="leave"))

    def test_white_is_still_painted_whatever_the_choice(self, fill):
        page = np.full((100, 160, 3), 250, np.uint8)
        mask = np.zeros((100, 160), np.uint8)
        mask[40:64, 40:120:12] = 255
        page[mask > 0] = 20
        fill(page, mask, Config(smart_fill_textured="leave"))
        assert fill.last_report["colour"] > 0 and fill.last_report["left"] == 0


class TestSmartFillSetting:
    def test_the_choice_reaches_the_config_and_survives_a_restart(self, qapp):
        from app.ui.settings.settings_page import SettingsPage
        from modules.utils.pipeline_config import get_config

        page = SettingsPage()
        try:
            page.ui.inpainter_combo.setCurrentText("Smart Fill")
            assert not page.ui.tools_page.smart_fill_textured_widget.isHidden()
            page.ui.tools_page.set_smart_fill_textured("heal")
            assert get_config(page).smart_fill_textured == "heal"
            page.save_settings()
        finally:
            page.deleteLater()

        reloaded = SettingsPage()
        try:
            reloaded.load_settings()
            assert reloaded.get_smart_fill_textured() == "heal"
            reloaded.ui.inpainter_combo.setCurrentText("AOT")
            assert reloaded.ui.tools_page.smart_fill_textured_widget.isHidden()
        finally:
            reloaded.deleteLater()

    def test_a_settings_page_without_the_choice_still_gets_a_config(self):
        from modules.utils.pipeline_config import get_config

        page = types.SimpleNamespace(
            ui=types.SimpleNamespace(tr=lambda s: s),
            get_hd_strategy_settings=lambda: {"strategy": "Resize", "resize_limit": 960},
        )
        assert get_config(page).smart_fill_textured == "model"
