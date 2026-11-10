"""A text outline is the letters grown by its width, at any width.

Reported as "strokes over 10 look terrible". The Qt painter drew an outline
as the text repeated at 16 offsets round a circle, which covers only the ring
at exactly that radius: from about 10 px the copies separate into sixteen
ghost words with holes between them. Skia stroked properly but left a pinhole
beside small contours (the dot of "!"). Qt is what draws any font the app
registered itself (every imported font), text being edited, and scaled or
warped text, so it is what users with their own fonts always saw.
"""

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QStyleOptionGraphicsItem

BACKGROUND = (120, 170, 220)
INK = (20, 20, 20)


@pytest.fixture(autouse=True)
def _engine_as_found():
    from core import text_engine

    before = text_engine.engine()
    yield
    text_engine.set_engine(before)


def _render(engine, width, text="WHAM! Hi."):
    from app.ui.canvas.text_item import TextBlockItem
    from core import text_engine

    text_engine.set_engine(engine)
    block = TextBlockItem(text=text, font_family="", font_size=54,
                          render_color=QColor(255, 255, 255), outline_color=None)
    block.set_font("", 54)
    block.set_color(QColor(255, 255, 255))
    block.setTextWidth(520)
    if width:
        block.set_outline(QColor(*INK), width)
    image = QImage(640, 200, QImage.Format.Format_ARGB32)
    image.fill(QColor(*BACKGROUND))
    painter = QPainter(image)
    painter.translate(50, 50)
    block.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()
    return np.frombuffer(image.constBits(), np.uint8).reshape(200, 640, 4)[..., [2, 1, 0]].astype(int)


def _grown(mask, radius):
    """`mask` dilated by a disc."""
    out = np.zeros_like(mask)
    r = int(radius)
    padded = np.pad(mask, r)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= radius * radius:
                out |= padded[r + dy:r + dy + mask.shape[0], r + dx:r + dx + mask.shape[1]]
    return out


def _engines():
    from core import skia_text

    return ["qt", "skia"] if skia_text.is_available() else ["qt"]


@pytest.mark.parametrize("width", [6, 14, 24])
def test_the_outline_is_solid_out_to_its_width(qapp, width):
    for engine in _engines():
        plain = _render(engine, 0)
        letters = np.abs(plain - BACKGROUND).sum(axis=2) > 120
        outlined = _render(engine, width)
        background = np.abs(outlined - BACKGROUND).sum(axis=2) < 60
        # Everything within the width of a letter (less the anti-aliased rim)
        # is outline or letter: no background shows through.
        must_be_covered = _grown(letters, width - 2)
        holes = int((must_be_covered & background).sum())
        assert holes == 0, f"{engine}: {holes} background pixels inside a {width}px outline"
        # ...and it does not reach past its width.
        reach = _grown(letters, width + 2)
        assert not (~reach & ~background).any(), f"{engine}: the outline spills past {width}px"


def test_the_fallback_copies_fill_the_band_too():
    """Vertical text is still drawn as displaced copies; they now cover the
    whole band, not one ring."""
    from app.ui.canvas.text_item import TextBlockItem

    thin = TextBlockItem._outline_offsets(2)
    assert len(thin) == 16
    wide = TextBlockItem._outline_offsets(24)
    radii = sorted({round((dx * dx + dy * dy) ** 0.5, 3) for dx, dy in wide})
    assert radii[-1] == 24 and len(radii) > 1
    assert max(b - a for a, b in zip([0.0] + radii, radii)) <= 8      # no empty band between rings
    outer = [(dx, dy) for dx, dy in wide if round((dx * dx + dy * dy) ** 0.5, 3) == 24]
    gap = 2 * 24 * np.sin(np.pi / len(outer))
    assert gap <= 3                                                    # neighbours on the ring overlap
    assert TextBlockItem._outline_offsets(0) == []


def test_an_outline_on_part_of_the_text_strokes_only_that_part(qapp):
    from PySide6.QtGui import QTextCursor
    from app.ui.canvas.text_item import TextBlockItem
    from core import text_engine

    text_engine.set_engine("qt")
    block = TextBlockItem(text="AB CD", font_family="", font_size=54,
                          render_color=QColor(255, 255, 255), outline_color=None)
    block.set_font("", 54)
    block.setTextWidth(520)
    whole = block.document_glyph_path()
    first = block.document_glyph_path(0, 2)
    rest = block.document_glyph_path(2, 5)
    assert not first.isEmpty() and not rest.isEmpty()
    assert first.boundingRect().right() < rest.boundingRect().right()
    assert first.elementCount() + rest.elementCount() == whole.elementCount()
