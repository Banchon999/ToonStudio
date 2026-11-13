"""The spot healing brush: heal a mark from texture found nearby, chosen
automatically — what the owner asked for after Smart Fill's no-model mode left
a smooth grey patch where screentone ran under the text.

`core.spot_heal` searches the page around a region for the placement whose
surroundings best match the region's own (FFT correlation over a band), then
heals from there. Used by the canvas brush (`spotheal`) and by Smart Fill's
"heal" choice for text over texture.
"""

import numpy as np
import pytest
from PySide6.QtCore import QPointF

from core import paint
from core.spot_heal import _fast_length, find_source_offset, spot_heal

H, W = 200, 320
yy, xx = np.mgrid[:H, :W]


def screentone():
    page = np.full((H, W, 3), 235, np.uint8)
    page[np.hypot((yy % 7) - 3, (xx % 7) - 3) < 1.8] = 70
    return page


def hatching():
    page = np.full((H, W, 3), 225, np.uint8)
    page[((xx + yy) % 9) < 2] = 60
    return page


def letters():
    """Two rows of bar-shaped "letters", grown past their rim as cleaning does."""
    mask = np.zeros((H, W), bool)
    for row in (60, 110):
        for x in range(60, 250, 24):
            mask[row:row + 30, x:x + 9] = True
    return mask


class TestFindingTheSource:
    @pytest.mark.parametrize("make", [screentone, hatching], ids=["screentone", "hatching"])
    def test_texture_carries_straight_through(self, make):
        truth = make()
        mask = letters()
        page = truth.copy()
        page[mask] = 15
        healed = spot_heal(page, mask)
        assert np.array_equal(healed[mask], truth[mask])
        assert np.array_equal(healed[~mask], page[~mask]), "nothing outside the marks moves"

    def test_a_smooth_fill_is_what_it_replaces(self):
        """The reason it exists: the smooth fill turns screentone into grey."""
        truth = screentone()
        mask = letters()
        page = truth.copy()
        page[mask] = 15
        smooth = paint.smooth_fill(page, mask)
        assert np.abs(smooth[mask].astype(int) - truth[mask]).mean() > 30

    def test_it_never_copies_another_mark(self):
        """A source on top of the other letters would paint letters back in."""
        truth = screentone()
        mask = letters()
        page = truth.copy()
        page[mask] = 15
        part = np.zeros_like(mask)
        part[60:90, 60:69] = True
        dx, dy = find_source_offset(page, part, avoid=mask)
        source, _ = paint.shifted(mask, dx, dy)
        assert not source[part].any()

    def test_with_nowhere_clean_to_copy_from_it_smooth_fills(self):
        page = np.full((40, 40, 3), 120, np.uint8)
        region = np.zeros((40, 40), bool)
        region[5:35, 5:35] = True
        assert find_source_offset(page, region, avoid=np.ones((40, 40), bool)) is None
        healed = spot_heal(page, region, avoid=np.ones((40, 40), bool))
        assert np.abs(healed[region].astype(int) - 120).max() <= 1

    def test_artwork_keeps_its_grain_and_tone(self):
        rng = np.random.default_rng(1)
        truth = np.clip(np.stack([120 + 50 * np.sin(xx / 37.0)] * 3, 2)
                        + rng.normal(0, 8, (H, W, 3)), 0, 255).astype(np.uint8)
        mask = letters()
        page = truth.copy()
        page[mask] = 15
        healed = spot_heal(page, mask)
        assert abs(healed[mask].astype(float).std() - truth[mask].astype(float).std()) < 5
        assert abs(healed[mask].astype(float).mean() - truth[mask].astype(float).mean()) < 5

    def test_a_far_corner_of_a_big_page_is_not_touched(self):
        page = np.zeros((3000, 800, 3), np.uint8)
        page[::4, ::4] = 200
        region = np.zeros((3000, 800), bool)
        region[100:120, 100:120] = True
        healed = spot_heal(page, region)
        assert np.array_equal(healed[600:], page[600:])

    def test_fft_sizes_are_smooth_numbers(self):
        for n in (1, 7, 11, 97, 129, 241, 1021):
            size = _fast_length(n)
            assert size >= n
            rest = size
            for p in (2, 3, 5):
                while rest % p == 0:
                    rest //= p
            assert rest == 1


class TestSmartFillHealsTexture:
    def test_screentone_under_text_comes_back(self):
        from modules.inpainting.schema import Config
        from modules.inpainting.smart_fill import SmartFill

        truth = screentone()
        mask = np.where(letters(), 255, 0).astype(np.uint8)
        page = truth.copy()
        page[mask > 0] = 15
        fill = SmartFill("cpu")
        fill._fallback_model = lambda *a, **k: pytest.fail("the model was asked")
        healed = fill(page, mask, Config(smart_fill_textured="heal"))
        assert fill.last_report["heal"] > 0
        # The letters' rims were grown into the dots as well: those come back too.
        assert np.abs(healed.astype(int) - truth).mean() < 0.5


# -- the canvas brush -------------------------------------------------------------

def _pump_until(qapp, condition, timeout_ms=20000):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        qapp.processEvents()
    return condition()


@pytest.fixture
def window(qapp, tmp_path):
    from PIL import Image

    import controller as controller_mod

    page = screentone()
    page[90:110, 140:200] = 10   # a mark across the dots
    win = controller_mod.ComicTranslate()
    path = str(tmp_path / "page.png")
    Image.fromarray(page).save(path)
    win.image_ctrl.thread_load_images([path])
    assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto() and win.undo_group.activeStack() is not None)
    dm = win.image_viewer.drawing_manager
    dm.paint_size = 34
    dm.paint_pressure_size = dm.paint_pressure_flow = False
    # Spot healing ignores these: a mark is healed whole, never faintly.
    dm.paint_hardness = 0.2
    dm.paint_opacity = 0.3
    yield win
    win._skip_close_prompt = True
    win.close()


class TestSpotHealingBrush:
    def test_a_stroke_heals_the_mark_back_into_screentone(self, window):
        dm = window.image_viewer.drawing_manager
        stack = window.undo_group.activeStack()
        count = stack.count()
        assert dm.pixel_press(QPointF(143, 100), "spotheal")
        for x in range(150, 200, 6):
            dm.pixel_move(QPointF(x, 100))
        assert dm.pixel_release() is not None
        after = window.image_viewer.get_image_array(include_patches=True)
        assert np.array_equal(after[90:110, 140:200], screentone()[90:110, 140:200])
        assert stack.count() == count + 1
        assert stack.text(stack.index() - 1) == "Spot Healing Brush"
        raw = window.image_viewer.get_image_array(include_patches=False)
        assert raw[100, 160].max() == 10, "the raw page is untouched"

    def test_it_needs_no_source_point(self, window):
        dm = window.image_viewer.drawing_manager
        dm.clone_source = None
        assert dm.pixel_press(QPointF(160, 100), "spotheal")
        assert dm.pixel_release() is not None

    def test_the_button_selects_the_tool_and_shows_only_its_options(self, window):
        window.spot_heal_button.click()
        assert window.image_viewer.current_tool == "spotheal"
        assert window.tool_buttons["spotheal"] is window.spot_heal_button
        assert window.paint_options.isVisibleTo(window)
        assert window.paint_pressure_button.isVisibleTo(window)
        assert not window.paint_hardness_slider.isVisibleTo(window)
        assert not window.paint_opacity_spin.isVisibleTo(window)
        assert not window.clone_aligned_check.isVisibleTo(window)
