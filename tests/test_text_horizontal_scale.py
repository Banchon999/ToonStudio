"""Horizontal scale: condense or widen a text item's letters.

Letterers squeeze a line to 85–95% so it fits a narrow bubble at full height;
PhotoCraft's and Photoshop's Character panels have it and ours did not. It
lives on the font, like letter spacing, so it has to survive every path that
rebuilds a font: a new family or size, undo, save and load, export.
"""

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QStyleOptionGraphicsItem


@pytest.fixture(autouse=True)
def _engine_as_found():
    """A window switches the process-wide text engine to the one in its
    settings; the files after this one expect to find it as they left it."""
    from core import text_engine

    before = text_engine.engine()
    yield
    text_engine.set_engine(before)


@pytest.fixture
def item(qapp):
    from app.ui.canvas.text_item import TextBlockItem

    block = TextBlockItem(text="CONDENSED LETTERING", font_family="", font_size=30,
                          render_color=QColor(0, 0, 0), outline_color=None)
    block.set_font("", 30)              # as the viewer does when it adds one
    block.setTextWidth(900)
    yield block


def _ink_width(block):
    image = QImage(900, 200, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    block.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(200, 900, 4)
    columns = np.nonzero((pixels[..., :3] < 128).any(axis=2).any(axis=0))[0]
    return int(columns.max() - columns.min() + 1)


def test_it_is_the_face_as_designed_to_begin_with(item):
    assert item.horizontal_scale == 100.0


def test_below_100_makes_the_line_narrower_and_above_wider(item, monkeypatch):
    # One engine for every measurement: at 100 Skia would draw it otherwise.
    from app.ui.canvas import skia_paint
    monkeypatch.setattr(skia_paint.text_engine, "paints_with_skia", lambda: False)
    normal = _ink_width(item)
    item.set_horizontal_scale(80)
    narrow = _ink_width(item)
    item.set_horizontal_scale(120)
    wide = _ink_width(item)
    assert narrow < normal * 0.9
    assert wide > normal * 1.1
    item.set_horizontal_scale(100)
    assert _ink_width(item) == normal


def test_a_new_family_or_size_keeps_it(item):
    item.set_horizontal_scale(80)
    item.set_font(item.font_family, 40)
    assert item.document().defaultFont().stretch() == 80
    block = item.document().firstBlock()
    assert block.begin().fragment().charFormat().font().stretch() == 80


def test_it_is_clamped_and_junk_is_ignored(item):
    item.set_horizontal_scale(5)
    assert item.horizontal_scale == item.MIN_HORIZONTAL_SCALE
    item.set_horizontal_scale(900)
    assert item.horizontal_scale == item.MAX_HORIZONTAL_SCALE
    item.set_horizontal_scale("wide")
    item.set_horizontal_scale(float("nan"))
    assert item.horizontal_scale == item.MAX_HORIZONTAL_SCALE


def test_it_is_saved_only_when_set_and_comes_back(item):
    from app.ui.canvas.text.text_item_properties import TextItemProperties

    assert "horizontal_scale" not in TextItemProperties.from_text_item(item).to_dict()
    item.set_horizontal_scale(85)
    state = TextItemProperties.from_text_item(item).to_dict()
    assert state["horizontal_scale"] == 85
    assert TextItemProperties.from_dict(state).horizontal_scale == 85
    assert TextItemProperties.from_dict({"horizontal_scale": "junk"}).horizontal_scale == 100.0


def test_skia_leaves_a_scaled_item_to_qt(item, monkeypatch):
    """Skia's paragraph has no horizontal scale: drawn by it, the item would
    come out at full width inside the box Qt measured for the narrow one."""
    from app.ui.canvas import skia_paint

    monkeypatch.setattr(skia_paint.text_engine, "paints_with_skia", lambda: True)
    monkeypatch.setattr(skia_paint, "has_family", lambda family: True)
    assert skia_paint.can_paint(item)
    item.set_horizontal_scale(90)
    assert not skia_paint.can_paint(item)


def test_a_style_preset_carries_it_but_not_as_part_of_the_look(item):
    from app.ui.canvas.text.presets import apply_preset_to_item, preset_from_item
    from modules.utils.text_presets import LOOK_FIELDS

    item.set_horizontal_scale(85)
    preset = preset_from_item(item, "Narrow")
    assert preset.horizontal_scale == 85
    # Newly rendered text was fitted at 100%: a default style must not refit it.
    assert "horizontal_scale" not in LOOK_FIELDS
    item.set_horizontal_scale(100)
    apply_preset_to_item(item, preset)
    assert item.horizontal_scale == 85


def test_the_toolbar_sets_it_as_one_undo_step_and_follows_the_selection(qapp):
    import controller as controller_mod
    from PySide6.QtGui import QUndoStack
    from app.ui.canvas.text.text_item_properties import TextItemProperties

    win = controller_mod.ComicTranslate()
    try:
        win.image_viewer.display_image_array(np.full((300, 400, 3), 220, np.uint8))
        stack = QUndoStack(win.undo_group)
        win.undo_group.addStack(stack)
        win.undo_group.setActiveStack(stack)
        text = win.image_viewer.add_text_item(TextItemProperties(
            text="<p>Hello there</p>", position=(10, 10), width=200,
            text_color=QColor("#101010"), outline_color=QColor("#ffffff")))
        win.curr_tblock_item = text

        win.horizontal_scale_dropdown.setCurrentText("9")       # on the way to "90"
        assert text.horizontal_scale == 100.0 and stack.count() == 0
        win.horizontal_scale_dropdown.setCurrentText("90")
        assert text.horizontal_scale == 90.0 and stack.count() == 1

        stack.undo()
        assert text.horizontal_scale == 100.0
        assert text.document().defaultFont().stretch() == 100
        stack.redo()
        assert text.horizontal_scale == 90.0
        assert text.document().defaultFont().stretch() == 90

        # Selecting an item shows its value without changing it.
        win.horizontal_scale_dropdown.blockSignals(True)
        win.horizontal_scale_dropdown.setCurrentText("100")
        win.horizontal_scale_dropdown.blockSignals(False)
        win.text_ctrl.set_values_for_blk_item(text)
        assert win.horizontal_scale_dropdown.currentText() == "90"
        assert text.horizontal_scale == 90.0 and stack.count() == 1
    finally:
        win._skip_close_prompt = True
        win.close()
