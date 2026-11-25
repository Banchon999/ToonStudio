"""Memory for a PC with 8 GB, with a browser or music alongside.

Measured on a 4-core CPU with the real models (owner's request: "people with
only 8 GB who listen to music on YouTube at the same time"):

* LaMa on OpenVINO kept the memory of every patch size it had seen — 2.3 GB
  over seven patch sizes, 5 GB for a full-size page — for under 5% of speed.
  It now runs on ONNX Runtime with the memory arena off: ~0.5 GB held between
  patches, about as fast.
* The models stay loaded after a step (detection, OCR, text segmentation
  ~420 MB, the inpainter), 1–1.5 GB in all. After 3 minutes with no work they
  are freed (Settings › Tools, on by default); with LaMa as the inpainter the
  process went from 1.28 GB to 0.21 GB, and the next step loaded them again
  as fast as the first, because a model file already checked this session is
  not hashed again.
"""

import os

import pytest


class TestChecksumMemo:
    def test_a_file_is_hashed_once_until_it_changes(self, tmp_path, monkeypatch):
        from modules.utils import download

        path = tmp_path / "model.onnx"
        path.write_bytes(b"weights" * 1000)
        calls = []
        real = download._sha256
        monkeypatch.setattr(download, "_sha256", lambda p: calls.append(p) or real(p))
        monkeypatch.setattr(download, "_hashed", {})
        first = download.calculate_sha256_checksum(str(path))
        assert download.calculate_sha256_checksum(str(path)) == first
        assert len(calls) == 1, "the second load does not read the file again"
        path.write_bytes(b"other weights")
        stat = os.stat(path)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        assert download.calculate_sha256_checksum(str(path)) != first
        assert len(calls) == 2, "a changed file is checked again"


def test_lama_runs_on_onnxruntime_with_the_memory_arena_off(monkeypatch):
    from modules.inpainting import lama as lama_mod

    made = {}
    monkeypatch.setattr(lama_mod.ModelDownloader, "get", lambda *a, **k: None)
    monkeypatch.setattr(lama_mod.ModelDownloader, "primary_path", lambda *a, **k: "lama.onnx")
    monkeypatch.setattr(lama_mod, "make_session",
                        lambda path, providers, sess_options=None: made.update(options=sess_options) or object())
    lama_mod.LaMa("cpu", backend="onnx")
    options = made["options"]
    assert options is not None and options.enable_cpu_mem_arena is False


def test_freeing_the_models_lets_go_of_the_text_segmentation_model_too():
    from modules.detection import text_seg_onnx
    from modules.detection.factory import DetectionEngineFactory
    from pipeline.main_pipeline import ComicTranslatePipeline

    text_seg_onnx._segmenter = object()
    DetectionEngineFactory._engines["test"] = object()
    pipeline = ComicTranslatePipeline.__new__(ComicTranslatePipeline)
    pipeline.block_detection = type("B", (), {"block_detector_cache": object()})()
    pipeline.inpainting = type("I", (), {"inpainter_cache": object(), "cached_inpainter_key": "x"})()
    pipeline.release_model_caches()
    assert text_seg_onnx._segmenter is None
    assert "test" not in DetectionEngineFactory._engines
    assert pipeline.inpainting.inpainter_cache is None and pipeline.block_detection.block_detector_cache is None


@pytest.fixture
def window(qapp):
    import controller

    win = controller.ComicTranslate()
    freed = []
    win.pipeline.release_model_caches = lambda: freed.append(True)
    win._freed = freed
    yield win
    win._skip_close_prompt = True
    win.close()


class TestIdleRelease:
    def test_a_finished_step_starts_the_idle_count(self, window, qapp):
        import controller

        assert window._model_idle_timer.interval() == controller.MODEL_IDLE_MS == 3 * 60 * 1000
        assert not window._model_idle_timer.isActive()
        done = []
        window.task_runner_ctrl.run_threaded(lambda: None, None, None, lambda: done.append(True))
        import time

        deadline = time.time() + 10
        while not done and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        qapp.processEvents()
        assert done and window._model_idle_timer.isActive()

    def test_idle_frees_the_models(self, window):
        window._release_idle_models()
        assert window._freed == [True]

    def test_not_while_something_runs(self, window, monkeypatch):
        monkeypatch.setattr(window, "models_busy", lambda: True)
        window._release_idle_models()
        assert window._freed == []
        assert window._model_idle_timer.isActive(), "tries again later"

    def test_the_setting_turns_it_off_and_is_saved(self, window):
        window.settings_page.ui.free_models_checkbox.setChecked(False)
        window._release_idle_models()
        assert window._freed == []
        assert window.settings_page.get_all_settings()["tools"]["free_models_when_idle"] is False
