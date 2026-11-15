"""The export watermark: a group's text and/or logo on every exported page.

The owner's choices: text, a logo, or both; one of nine positions with a
margin; every page; only on export — the project is not changed, and a PSD
gets it as a layer of its own. Drawn once on the GUI thread
(`app.ui.watermark.build_stamp`), placed by the workers without Qt
(`core.watermark.WatermarkStamp`).
"""

import os

import numpy as np
import pytest
from PIL import Image

from core.watermark import (
    POSITIONS, REFERENCE_WIDTH, WatermarkSettings, WatermarkStamp, composite, place,
)


# -- placing (Qt-free) -------------------------------------------------------------

class TestPlacing:
    @pytest.mark.parametrize("position, expected", [
        ("top-left", (10, 10)), ("top-center", (40, 10)), ("top-right", (70, 10)),
        ("middle-left", (10, 90)), ("center", (40, 90)), ("middle-right", (70, 90)),
        ("bottom-left", (10, 170)), ("bottom-center", (40, 170)), ("bottom-right", (70, 170)),
    ])
    def test_each_of_the_nine_positions(self, position, expected):
        assert place(100, 200, 20, 20, position, 10) == expected

    def test_a_mark_bigger_than_the_page_starts_at_its_corner(self):
        assert place(50, 50, 80, 80, "bottom-right", 5) == (0, 0)

    def test_compositing_mixes_by_alpha_and_clips_at_the_edge(self):
        page = np.zeros((10, 10, 3), np.uint8)
        mark = np.zeros((4, 4, 4), np.uint8)
        mark[..., :3] = 200
        mark[..., 3] = 128
        out = composite(page, mark, 8, 8)   # hangs off the bottom-right corner
        assert out[9, 9, 0] == round(200 * 128 / 255)
        assert out[7, 7].sum() == 0 and out.shape == page.shape
        assert page.sum() == 0, "the page given is not changed"


class TestSettings:
    def test_values_read_back_from_qsettings_as_strings(self):
        s = WatermarkSettings.from_dict({"enabled": "true", "opacity": "250", "text_size": "4.5",
                                          "position": "nowhere", "kind": "both", "text": "MAX"})
        assert s.enabled is True and s.opacity == 100 and s.text_size == 4.5
        assert s.position == "bottom-right" and s.kind == "both"
        assert WatermarkSettings.from_dict({"enabled": "false"}).enabled is False

    def test_it_is_active_only_when_on_and_with_something_to_draw(self):
        assert not WatermarkSettings(enabled=True, kind="text", text="  ").is_active()
        assert not WatermarkSettings(enabled=False, kind="text", text="MAX").is_active()
        assert WatermarkSettings(enabled=True, kind="text", text="MAX").is_active()
        assert not WatermarkSettings(enabled=True, kind="image", text="MAX").is_active()


class TestStampScaling:
    def _white_square_stamp(self):
        rgba = np.zeros((100, 400, 4), np.uint8)
        rgba[20:80, 20:380, :3] = 255
        rgba[20:80, 20:380, 3] = 255
        return WatermarkStamp(rgba=rgba, position="bottom-right", margin=2.0)

    def test_its_size_follows_the_page_width(self):
        stamp = self._white_square_stamp()
        _x, _y, small = stamp.for_page(1000, 1500)
        _x, _y, tall = stamp.for_page(1000, 8000)    # a webtoon page, as wide
        assert small.shape == tall.shape == (50, 200, 4)
        x, y, _mark = stamp.for_page(1000, 1500)
        assert (x, y) == (1000 - 200 - 20, 1500 - 50 - 20)

    def test_shrinking_leaves_no_dark_fringe_round_white_lettering(self):
        """Resampled as straight alpha, the black of the transparent pixels
        bleeds into the edge of white text and outlines it in grey."""
        _x, _y, mark = self._white_square_stamp().for_page(REFERENCE_WIDTH // 3, 900)
        edge = (mark[..., 3] > 0) & (mark[..., 3] < 255)
        assert edge.any()
        assert mark[edge][:, :3].min() >= 250

    def test_scaling_never_makes_it_more_opaque_than_set(self, qapp):
        """Found opening an export in Photopea: Lanczos overshoot took a 70%
        watermark's alpha from 178 to 198."""
        from app.ui.watermark import build_stamp

        stamp = build_stamp(WatermarkSettings(enabled=True, kind="text", text="MAXSCANS", text_size=4, opacity=70))
        for width in (500, 1000, 1999, 2600):
            _x, _y, mark = stamp.for_page(width, 1500)
            assert mark[..., 3].max() <= stamp.rgba[..., 3].max() <= 179, width

    def test_apply_stamps_the_page_and_leaves_the_rest(self):
        page = np.full((1500, 1000, 3), 30, np.uint8)
        out = self._white_square_stamp().apply(page)
        x, y, mark = self._white_square_stamp().for_page(1000, 1500)
        assert out[y + 25, x + 100].min() == 255
        assert np.array_equal(out[:1000], page[:1000])


# -- drawing (Qt) ---------------------------------------------------------------

@pytest.fixture
def logo(tmp_path):
    image = np.zeros((60, 120, 4), np.uint8)
    image[..., 0] = 255          # red, half transparent
    image[..., 3] = 128
    path = tmp_path / "logo.png"
    Image.fromarray(image, "RGBA").save(path)
    return str(path)


class TestDrawing:
    def test_text_is_drawn_with_its_outline_and_opacity(self, qapp):
        from app.ui.watermark import build_stamp

        stamp = build_stamp(WatermarkSettings(enabled=True, kind="text", text="MAXSCANS", opacity=50,
                                              text_color="#ffffff", outline_color="#000000", outline_width=3))
        alpha = stamp.rgba[..., 3]
        assert alpha.max() <= 128 and alpha.max() >= 120, "opacity 50% caps the alpha"
        solid = alpha >= 120
        assert stamp.rgba[solid][:, :3].max() == 255 and stamp.rgba[solid][:, :3].min() == 0, \
            "white letters and a black outline"

    def test_a_logo_keeps_its_own_transparency_times_the_opacity(self, qapp, logo):
        from app.ui.watermark import build_stamp

        stamp = build_stamp(WatermarkSettings(enabled=True, kind="image", image_path=logo,
                                              image_size=10, opacity=100))
        assert stamp.rgba.shape[1] == REFERENCE_WIDTH * 10 // 100
        assert abs(int(stamp.rgba[..., 3].max()) - 128) <= 1
        assert stamp.rgba[stamp.rgba[..., 3] > 0][:, 0].min() >= 250

    def test_logo_and_text_are_stacked(self, qapp, logo):
        from app.ui.watermark import build_stamp

        text = build_stamp(WatermarkSettings(enabled=True, kind="text", text="MAX"))
        both = build_stamp(WatermarkSettings(enabled=True, kind="both", text="MAX", image_path=logo))
        assert both.rgba.shape[0] > text.rgba.shape[0]

    def test_off_empty_or_a_missing_logo_draws_nothing(self, qapp, tmp_path):
        from app.ui.watermark import build_stamp

        assert build_stamp(WatermarkSettings(enabled=False, kind="text", text="MAX")) is None
        assert build_stamp(WatermarkSettings(enabled=True, kind="text", text="")) is None
        assert build_stamp(WatermarkSettings(enabled=True, kind="image",
                                             image_path=str(tmp_path / "gone.png"))) is None

    def test_a_chosen_logo_is_copied_so_moving_the_original_does_not_break_it(self, qapp, logo):
        from app.ui.watermark import keep_logo

        kept = keep_logo(logo)
        os.remove(logo)
        assert os.path.isfile(kept) and kept != logo


# -- the settings page ------------------------------------------------------------

def test_the_settings_survive_a_restart(qapp, logo):
    from app.ui.settings.settings_page import SettingsPage

    wanted = WatermarkSettings(enabled=True, kind="both", text="ทีมแปล MAX", image_path=logo,
                               text_size=4.5, opacity=40, position="top-left", margin=3.0)
    page = SettingsPage()
    try:
        page.ui.export_page.watermark_section.set_settings(wanted)
        page.save_settings()
    finally:
        page.deleteLater()
    reloaded = SettingsPage()
    try:
        reloaded.load_settings()
        got = reloaded.get_watermark_settings()
        for name in ("enabled", "kind", "text", "image_path", "text_size", "opacity", "position", "margin"):
            assert getattr(got, name) == getattr(wanted, name), name
    finally:
        reloaded.deleteLater()


# -- exports -------------------------------------------------------------------------

def _pump_until(qapp, condition, timeout_ms=20000):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        qapp.processEvents()
    return condition()


@pytest.fixture
def window(qapp, tmp_path):
    import controller as controller_mod

    page = np.full((900, 600, 3), 40, np.uint8)
    path = str(tmp_path / "001.png")
    Image.fromarray(page).save(path)
    win = controller_mod.ComicTranslate()
    win.image_ctrl.thread_load_images([path])
    assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto())
    win.settings_page.ui.export_page.watermark_section.set_settings(WatermarkSettings(
        enabled=True, kind="text", text="MAXSCANS", text_size=5, opacity=100, position="bottom-right"))
    yield win
    win._skip_close_prompt = True
    win.close()


def test_an_exported_page_carries_it_and_the_project_does_not(window, tmp_path):
    ctrl = window.project_ctrl
    out = tmp_path / "out"
    state = ctrl._build_all_pages_current_state()
    ctrl.save_and_make_worker([{"output_path": str(out), "page_indices": [0], "folder": True}],
                              state, ctrl.watermark_stamp())
    (written,) = os.listdir(out)
    page = np.asarray(Image.open(out / written).convert("RGB"))
    corner, rest = page[780:, 330:], page[:600]
    assert (corner.min(axis=2) >= 250).sum() > 50, "white letters in the bottom-right corner"
    assert rest.max() <= 41, "nothing elsewhere"
    assert window.image_viewer.get_image_array(include_patches=True)[780:, 330:].max() <= 41, \
        "the canvas and project are untouched"


def test_the_psd_gets_it_as_its_own_top_layer(window, tmp_path):
    psd_tools = pytest.importorskip("psd_tools")
    from app.controllers import psd_exporter

    if not psd_exporter.psd_support_available():
        pytest.skip("PhotoshopAPI has no wheel for this platform")
    ctrl = window.project_ctrl
    pages = ctrl._gather_psd_pages(ctrl._build_all_pages_current_state(), ctrl.watermark_stamp())
    path = psd_exporter.export_psd_pages(str(tmp_path), pages, "bundle")
    psd = psd_tools.PSDImage.open(path)
    names = [layer.name for layer in psd]
    assert names[-1] == "Watermark", names
    layer = psd[-1]
    pixels = np.asarray(layer.numpy())
    assert pixels.shape[-1] == 4 and 0 < pixels[..., 3].mean() < 1, "transparent around the letters"
    # The flattened preview (what every reader but Photoshop shows) has it too.
    preview = np.asarray(psd.topil().convert("RGB"))
    assert (preview[780:, 330:].min(axis=2) >= 250).sum() > 50
    assert preview[:600].max() <= 41
    left, top = layer.offset
    assert left > 300 and top > 750, "bottom-right"
