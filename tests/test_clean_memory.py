"""Cleaning a very tall page must not need many times the page in memory.

Reported from the 3.4.3 test build: the multi-page Clean stopped with
"MemoryError: Unable to allocate 600. MiB for an array with shape
(32767, 800, 3) and data type float64" in `imk.convert_scale_abs`. Measured
on a page that size (AOT, Resize 960): one Clean peaked at 1 950 MiB for a
75 MiB page. Two places did it:

- `convert_scale_abs` turned the uint8 page the inpainter returns into three
  float64 copies (scale, abs, clip) to give back the same uint8 page:
  +1 875 MiB.
- The Resize strategy pasted the untouched pixels back with a 2-D boolean
  index into a 3-D array, which builds an int64 index for every kept pixel:
  +420 MiB.

After both: 252 MiB, with every patch bit-identical.
"""

import tracemalloc

import numpy as np
import pytest

import imkit as imk
from modules.inpainting.base import InpaintModel
from modules.inpainting.schema import Config, HDStrategy


def _old_convert_scale_abs(array, alpha=1.0, beta=0.0):
    """The implementation that ran out of memory, kept as the reference."""
    return np.clip(np.abs(array * alpha + beta), 0, 255).astype(np.uint8)


def _peak_mib(fn, *args, **kwargs):
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base, _ = tracemalloc.get_traced_memory()
        result = fn(*args, **kwargs)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, (peak - base) / 2**20


class TestConvertScaleAbs:
    @pytest.mark.parametrize("dtype", [np.uint8, np.int16, np.int32, np.float32, np.float64])
    @pytest.mark.parametrize("alpha, beta", [(1.0, 0.0), (1.5, -20.0), (-0.7, 3.0), (2, 0)])
    def test_gives_exactly_what_it_always_gave(self, dtype, alpha, beta):
        rng = np.random.default_rng(1)
        array = (rng.normal(100, 120, (37, 23, 3))).astype(dtype)
        got = imk.convert_scale_abs(array, alpha, beta)
        assert got.dtype == np.uint8 and got.shape == array.shape
        assert np.array_equal(got, _old_convert_scale_abs(array, alpha, beta))

    def test_a_tall_float_page_is_converted_block_by_block_to_the_same_bytes(self):
        rng = np.random.default_rng(2)
        page = rng.uniform(-40, 300, (5000, 64, 3))
        assert np.array_equal(imk.convert_scale_abs(page), _old_convert_scale_abs(page))
        assert np.array_equal(imk.convert_scale_abs(page[:, :, 0]), _old_convert_scale_abs(page[:, :, 0]))

    def test_the_result_is_a_new_array(self):
        """Callers cut patches from it while the page they passed is still in use."""
        page = np.full((10, 10, 3), 7, np.uint8)
        out = imk.convert_scale_abs(page)
        out[:] = 0
        assert page.max() == 7

    def test_a_uint8_page_costs_one_copy_not_three_float64_ones(self):
        page = np.full((8000, 800, 3), 200, np.uint8)       # 18 MiB
        _out, peak = _peak_mib(imk.convert_scale_abs, page)
        assert peak <= page.nbytes / 2**20 * 1.2, f"{peak:.0f} MiB for a {page.nbytes / 2**20:.0f} MiB page"

    def test_a_float_page_is_never_copied_whole_in_float64(self):
        page = np.full((8000, 800, 3), 200.0)                # 146 MiB of float64
        _out, peak = _peak_mib(imk.convert_scale_abs, page)
        # The uint8 result (18 MiB) plus one block of rows.
        assert peak <= 18 + 40, f"{peak:.0f} MiB"


class _Blur(InpaintModel):
    """An inpainter that needs no model: fills the hole with the page's mean."""

    name = "blur"

    def init_model(self, device, **kwargs):
        pass

    @staticmethod
    def is_downloaded():
        return True

    def forward(self, image, mask, config):
        out = image.astype(np.float64).copy()
        out[mask[..., 0] > 0 if mask.ndim == 3 else mask > 0] = image.mean(axis=(0, 1))
        return out


def _resize_config():
    return Config(hd_strategy=HDStrategy.RESIZE, hd_strategy_resize_limit=960)


def _tall_page(height=12000, width=800):
    image = np.full((height, width, 3), 230, np.uint8)
    image[::5] = 90
    mask = np.zeros((height, width), np.uint8)
    for y in range(300, height - 300, 1500):
        mask[y:y + 160, 250:550] = 255
    return image, mask


class TestResizeStrategyPaste:
    def test_pixels_outside_the_mask_come_back_exactly_and_the_hole_is_filled(self):
        image, mask = _tall_page(3000)
        result = _Blur("cpu")(image, mask, _resize_config())
        assert result.dtype == np.uint8 and result.shape == image.shape
        assert np.array_equal(result[mask < 127], image[mask < 127])
        assert not np.array_equal(result[mask >= 127], image[mask >= 127])

    def test_it_matches_the_boolean_index_it_replaced(self):
        image, mask = _tall_page(3000)
        result = _Blur("cpu")(image, mask, _resize_config())
        # Recreate the result the old way: upscale, then index-paste.
        reference = result.copy()
        reference[mask < 127] = image[mask < 127]
        assert np.array_equal(result, reference)

    def test_a_tall_page_is_not_held_several_times_over(self):
        image, mask = _tall_page()                           # 27 MiB page
        _result, peak = _peak_mib(_Blur("cpu"), image, mask, _resize_config())
        page = image.nbytes / 2**20
        # The upscaled result and PIL's copy of it during the resize, and the
        # mask test; the boolean index alone used to add 2 × 8 bytes a pixel.
        assert peak <= page * 2.6, f"{peak:.0f} MiB for a {page:.0f} MiB page"
