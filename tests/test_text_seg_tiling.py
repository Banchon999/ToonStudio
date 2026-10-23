"""A tall page is segmented in windows, not squeezed into one 1024 input.

The network's input is 1024x1024, so a whole 800x5000 webtoon page went in at
a fifth of its size. On real pages that left lettering with no mask at all —
"IT LOOKS" at the foot of a page, a watermark at its edge — and Segment drew
nothing there, so Clean never touched it. These tests stand a runner in for
the model: one that marks wherever the picture it is handed is bright, which
is exactly what downscaling takes away from thin lettering.
"""

import numpy as np
import pytest

from modules.detection import text_seg_onnx
from modules.detection.text_seg_onnx import SLOW_TILE_ASPECT, INPUT_SIZE, ComicTextSegmenter, tile_rows


class BrightRunner:
    """Marks every input pixel brighter than half: thin strokes vanish when shrunk."""

    def __init__(self, backend="openvino"):
        self.backend = backend
        self.calls = 0

    def run(self, tensor):
        self.calls += 1
        return (tensor[:, :1] > 0.5).astype(np.float32)


class CountingRunner:
    """Answers the n-th call with probability n/10 everywhere."""

    backend = "openvino"

    def __init__(self):
        self.calls = 0

    def run(self, tensor):
        self.calls += 1
        return np.full((1, 1, INPUT_SIZE, INPUT_SIZE), self.calls / 10, np.float32)


def segmenter(runner, device="cpu"):
    seg = ComicTextSegmenter()
    seg.session = runner
    seg._device = device
    return seg


def strip_with_a_thin_line(height=5000, width=800, row=4970):
    page = np.zeros((height, width, 3), np.uint8)
    page[row:row + 2, 300:500] = 255
    return page


class TestWindows:
    def test_an_ordinary_page_goes_in_whole(self):
        assert tile_rows(1200, 800) == [(0, 1200)]
        assert tile_rows(800, 1600) == [(0, 800)]

    def test_up_to_twice_as_tall_as_wide_goes_in_whole(self):
        assert tile_rows(1600, 800) == [(0, 1600)]
        assert len(tile_rows(1601, 800)) > 1

    def test_a_strip_is_covered_row_for_row_by_page_shaped_windows(self):
        windows = tile_rows(5000, 800)
        assert windows[0][0] == 0 and windows[-1][1] == 5000
        assert all(bottom - top == 1200 for top, bottom in windows)
        covered = np.zeros(5000, bool)
        for top, bottom in windows:
            covered[top:bottom] = True
        assert covered.all()

    def test_neighbours_overlap_by_more_than_a_line_of_text(self):
        windows = tile_rows(15000, 800)
        for (_, bottom), (top, _) in zip(windows, windows[1:]):
            assert bottom - top >= 0.2 * 1200

    def test_a_very_narrow_strip_is_not_cut_into_slivers(self):
        windows = tile_rows(3000, 40)
        assert all(bottom - top == INPUT_SIZE // 2 for top, bottom in windows)
        assert len(windows) < 10


class TestSegment:
    def test_an_ordinary_page_is_one_call_and_unchanged(self):
        rng = np.random.default_rng(0)
        page = rng.integers(0, 255, (1200, 800, 3), dtype=np.uint8)
        runner = BrightRunner()
        seg = segmenter(runner)
        out = seg.segment(page)
        assert runner.calls == 1
        assert np.array_equal(out, seg._segment_whole(page))

    def test_thin_lettering_at_the_foot_of_a_strip_is_found(self):
        page = strip_with_a_thin_line()
        out = segmenter(BrightRunner()).segment(page)
        assert out[4970:4972, 320:480].max() > 127

    def test_squeezed_whole_the_same_lettering_is_lost(self, monkeypatch):
        # What every tall page got before: the line is gone at a fifth of its size.
        monkeypatch.setattr(text_seg_onnx, "TILE_MIN_ASPECT", 1e9)
        page = strip_with_a_thin_line()
        out = segmenter(BrightRunner()).segment(page)
        assert out[4970:4972, 320:480].max() <= 127

    def test_the_whole_page_and_each_window_are_read_and_the_higher_value_kept(self):
        runner = CountingRunner()
        windows = tile_rows(5000, 800)
        out = segmenter(runner).segment(np.zeros((5000, 800, 3), np.uint8))
        assert runner.calls == 1 + len(windows)
        assert out.shape == (5000, 800)
        # Call 1 (the whole page) answers 0.1, window n call n + 1; later
        # windows sit lower, so every row takes the last window covering it.
        for n, (top, bottom) in enumerate(windows, start=1):
            next_top = windows[n][0] if n < len(windows) else bottom
            assert np.all(out[top:next_top] == np.uint8((n + 1) / 10 * 255))

    def test_what_the_whole_page_pass_finds_is_kept(self):
        # Squeezed, the network marks the glow around white lettering, which
        # sharp windows leave out; the windows are added to that pass.
        class WholePageOnly:
            backend = "openvino"
            calls = 0

            def run(self, tensor):
                self.calls += 1
                value = 1.0 if self.calls == 1 else 0.0
                return np.full((1, 1, INPUT_SIZE, INPUT_SIZE), value, np.float32)

        out = segmenter(WholePageOnly()).segment(np.zeros((5000, 800, 3), np.uint8))
        assert out.min() == 255

    def test_a_greyscale_strip_works(self):
        page = strip_with_a_thin_line()[..., 0]
        out = segmenter(BrightRunner()).segment(page)
        assert out.shape == (5000, 800)
        assert out[4970:4972, 320:480].max() > 127


class TestSlowBackend:
    """ONNX Runtime on the CPU costs ~40 s a call, so it gets fewer, taller windows."""

    def test_onnxruntime_on_the_cpu_reads_three_windows_of_a_tall_page(self):
        runner = BrightRunner(backend="onnxruntime")
        out = segmenter(runner, "cpu").segment(strip_with_a_thin_line())
        assert len(tile_rows(5000, 800, SLOW_TILE_ASPECT)) == 3
        assert runner.calls == 1 + 3
        assert out[4970:4972, 320:480].max() > 127

    def test_a_webtoon_chunk_stays_one_call_there(self):
        runner = BrightRunner(backend="onnxruntime")
        segmenter(runner, "cpu").segment(np.zeros((2400, 800, 3), np.uint8))
        assert runner.calls == 1

    @pytest.mark.parametrize("backend, device", [("openvino", "cpu"), ("onnxruntime", "cuda")])
    def test_fast_backends_use_page_shaped_windows(self, backend, device):
        runner = BrightRunner(backend=backend)
        segmenter(runner, device).segment(strip_with_a_thin_line())
        assert len(tile_rows(5000, 800)) == 5
        assert runner.calls == 1 + 5
