"""Text in a font only Qt knows is not cut at the end of each line.

The app registers its bundled face and every font a user imports with Qt
alone (`QFontDatabase.addApplicationFont`); Skia, the default engine, reads the
system's fonts and laid such text out in a substitute face. Qt sized the box,
Skia drew wider, and the last letters of every line fell outside the box:
"ไปไหน" rendered as "ไปไห", "ประภาคาร" as "ประภาคา", until the user widened
the box by hand. Found while drawing the README's demo page in the bundled
IBM Plex Sans Thai; the same happens with a font imported in Settings.
"""

from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.canvas.save_renderer import build_text_item
from core import text_engine, text_measure
from core.skia_text import SkiaTextMeasurer, has_family, is_available
from core.text_measure import Alignment, LayoutDirection, TextStyle
from core.text_style import build_text_item_state

pytestmark = pytest.mark.skipif(not is_available(), reason="skia-python not usable here")

APP_FONT = "IBM Plex Sans Thai"      # bundled in resources/fonts/ui, registered with Qt only
UI_FONT_DIR = Path(__file__).resolve().parent.parent / "resources" / "fonts" / "ui"
TEXT = "เรากำลังจะไปไหน\nกันเหรอ จุน?"


@pytest.fixture
def app_font(qapp):
    """The bundled face, registered with Qt for this test only.

    Registered and removed here rather than through `load_ui_fonts`, which
    keeps it for the process: once Qt has it, Qt's fallback for Thai in a
    blank family picks it while Skia's cannot, and `test_skia_measurer`'s
    Thai case (run right after this file) measured 58 px apart on CI.
    """
    if has_family(APP_FONT):
        pytest.skip("this machine has the font installed system-wide, so Skia sees it")
    font_id = QtGui.QFontDatabase.addApplicationFont(str(UI_FONT_DIR / "IBMPlexSansThai-Regular.ttf"))
    if font_id == -1 or APP_FONT not in QtGui.QFontDatabase.applicationFontFamilies(font_id):
        pytest.skip("bundled UI font did not load")
    yield APP_FONT
    QtGui.QFontDatabase.removeApplicationFont(font_id)


@pytest.fixture
def skia_engine():
    previous = text_engine.engine()
    text_engine.set_engine(text_engine.SKIA)
    text_measure.set_measurer(None)
    yield
    text_engine.set_engine(previous)
    text_measure.set_measurer(None)


def test_has_family_tells_system_fonts_from_unknown_ones():
    import skia

    system = skia.FontMgr().getFamilyName(0)
    assert has_family(system)
    assert not has_family("No Such Font Family 7f3a")
    assert has_family("")          # the measurer's own default


def test_the_skia_measurer_measures_an_app_font_as_qt_lays_it_out(app_font):
    from app.ui.canvas.text.qt_measurer import QtTextMeasurer

    style = TextStyle(font_family=app_font, font_size=19)
    assert SkiaTextMeasurer().measure(TEXT, style) == QtTextMeasurer().measure(TEXT, style)


def _item(font):
    state = build_text_item_state(
        object_id="", text=TEXT, font_family=font, font_size=19, text_color="#141418",
        alignment=Alignment.Center, line_spacing=1.0, outline_color="#ffffff", outline_width=2.0,
        bold=False, italic=False, underline=False, position=(10.0, 10.0), rotation=0.0,
        scale=1.0, transform_origin=None, width=None, height=None,
        direction=LayoutDirection.LeftToRight, vertical=False, outline=True)
    return build_text_item(state)


def _paint(item, engine):
    text_engine.set_engine(engine)
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(item)
    image = QtGui.QImage(320, 120, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(128, 128, 128))
    painter = QtGui.QPainter(image)
    scene.render(painter, QtCore.QRectF(0, 0, 320, 120), QtCore.QRectF(0, 0, 320, 120))
    painter.end()
    scene.removeItem(item)
    bits = image.constBits()
    return np.frombuffer(bits, np.uint8).reshape(120, image.bytesPerLine() // 4, 4)[:, :320].copy()


def test_an_app_font_draws_the_same_under_skia_as_under_qt(app_font, skia_engine):
    """Under Skia the substitute face's wider glyphs were clipped at the box."""
    item = _item(app_font)
    assert not __import__("app.ui.canvas.skia_paint", fromlist=["x"]).can_paint(item)
    qt_pixels = _paint(_item(app_font), text_engine.QT)
    skia_pixels = _paint(item, text_engine.SKIA)
    assert np.array_equal(qt_pixels, skia_pixels)


def test_a_system_font_still_goes_through_skia(skia_engine, qapp):
    import skia

    from app.ui.canvas import skia_paint

    system = skia.FontMgr().getFamilyName(0)
    assert skia_paint.can_paint(_item(system))
