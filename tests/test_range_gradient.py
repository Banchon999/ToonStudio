"""A gradient on just the words picked, not the whole text.

Pick words in the translation box (or on the canvas) and click a gradient:
only those words fade, across their own box. The gradient lives in those
characters' format, so it follows edits, survives saving and undo, and keeps
its place under a whole-text gradient being turned on and off.
"""

import numpy as np
import pytest
from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTextCursor
from PySide6.QtWidgets import QStyleOptionGraphicsItem


@pytest.fixture(autouse=True)
def _qt_engine():
    """Range gradients are painted by Qt (Skia hands such text over); pin the
    engine so measurements here do not depend on the previous test."""
    from core import text_engine

    before = text_engine.engine()
    text_engine.set_engine(text_engine.QT)
    yield
    text_engine.set_engine(before)


def _item(qapp, text="HELLO BIG WORLD"):
    from app.ui.canvas.text_item import TextBlockItem

    item = TextBlockItem(text="")
    item.set_plain_text(text)
    item.set_font("DejaVu Sans", 30)
    item.setTextWidth(500)
    return item


def _columns(item, width=520, height=80):
    """Mean colour of each column of ink: (x, (r, g, b))."""
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    item.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(height, image.bytesPerLine() // 4, 4)[:, :width, 2::-1]
    ink = pixels.astype(int).sum(axis=2) < 600
    return {x: pixels[ink[:, x], x].mean(axis=0) for x in range(width) if ink[:, x].sum() > 2}


class TestItem:
    def test_only_the_words_picked_fade(self, qapp):
        item = _item(qapp)
        item.set_range_gradient(6, 9, "#ff0000", "#0000ff", 0)
        rect = item._range_rect(6, 9)
        columns = _columns(item)
        inside = [c for x, c in columns.items() if rect.left() + 2 < x < rect.right() - 2]
        outside = [c for x, c in columns.items() if x < rect.left() - 2 or x > rect.right() + 2]
        assert inside and outside
        # Red at the word's start, blue at its end: one sweep across the word.
        assert inside[0][0] > inside[0][2] and inside[-1][2] > inside[-1][0]
        assert all(abs(c[0] - c[2]) < 30 for c in outside), "the other words keep their (black) colour"

    def test_the_range_follows_edits(self, qapp):
        item = _item(qapp)
        item.set_range_gradient(6, 9, "#ff0000", "#0000ff", 0)
        cursor = QTextCursor(item.document())
        cursor.insertText("AA ")  # before it
        assert item.range_gradients[0][:2] == (9, 12)
        cursor.setPosition(11)
        cursor.insertText("XX")  # inside it
        assert item.range_gradients[0][:2] == (9, 14)
        assert item.toPlainText()[9:14] == "BIXXG"

    def test_it_survives_the_html_a_project_and_undo_keep(self, qapp):
        from app.ui.canvas.text_item import TextBlockItem

        item = _item(qapp)
        item.set_range_gradient(6, 9, "#ff0000", "#0000ff", 30)
        copy = TextBlockItem(text="")
        copy.set_text(item.toHtml(), 300)  # narrower: laid out again
        assert copy.range_gradients == item.range_gradients

    def test_a_whole_text_gradient_lies_underneath(self, qapp):
        item = _item(qapp)
        item.set_range_gradient(6, 9, "#ff0000", "#0000ff", 0)
        item.set_gradient(True, QColor("#00ff00"), 90)
        assert [r[:2] for r in item.range_gradients] == [(6, 9)]
        item.set_gradient(False)
        assert [r[:2] for r in item.range_gradients] == [(6, 9)]

    def test_new_line_breaks_resize_it_to_its_words(self, qapp):
        item = _item(qapp)
        item.set_range_gradient(6, 15, "#ff0000", "#0000ff", 0)
        wide = item._range_rect(6, 15)
        item.setTextWidth(140)
        narrow = item._range_rect(6, 15)
        assert narrow.height() > wide.height(), "BIG and WORLD now on two lines"
        brush = QTextCursor(item.document())
        brush.setPosition(7)
        from app.ui.canvas.text_item import _gradient_geometry

        start_x, _y, end_x, _y2 = _gradient_geometry(brush.charFormat().foreground())
        assert abs((end_x - start_x) - narrow.width()) < 1.0

    def test_taking_it_off_gives_the_words_the_items_colour(self, qapp):
        item = _item(qapp)
        item.set_range_gradient(0, 15, "#ff0000", "#0000ff", 0)
        assert item.remove_range_gradients(6, 9)
        assert [r[:2] for r in item.range_gradients] == [(0, 6), (9, 15)]
        cursor = QTextCursor(item.document())
        cursor.setPosition(7)
        assert cursor.charFormat().foreground().style() == Qt.BrushStyle.SolidPattern
        assert not item.remove_range_gradients(6, 9), "nothing left there to take off"

    def test_skia_hands_such_text_to_qt(self, qapp):
        from app.ui.canvas import skia_paint

        item = _item(qapp)
        assert not skia_paint._needs_qt_layout(item)
        item.set_range_gradient(6, 9, "#ff0000", "#0000ff", 0)
        assert skia_paint._needs_qt_layout(item)


@pytest.fixture
def window(qapp):
    import controller

    win = controller.ComicTranslate()
    win.image_viewer.display_image_array(np.full((300, 600, 3), 230, dtype=np.uint8))
    stack = QtGui.QUndoStack()
    win.undo_group.addStack(stack)
    win.undo_group.setActiveStack(stack)
    win._stack = stack
    win.type_text_button.setChecked(True)
    win.toggle_type_text_tool()
    win.image_viewer.add_text_requested.emit(QPointF(40, 60))
    item = win.image_viewer.text_items[-1]
    item.textCursor().insertText("HELLO BIG WORLD")
    win.text_ctrl._commit_pending_text_command()
    cursor = item.textCursor()
    cursor.clearSelection()
    item.setTextCursor(cursor)
    win.set_tool(None)
    item.setSelected(True)
    win.text_ctrl.on_text_item_selected(item)
    QtWidgets.QApplication.processEvents()
    win._item = item
    yield win
    win._skip_close_prompt = True
    win.close()


def _select_in_box(win, start, end):
    cursor = win.t_text_edit.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    win.t_text_edit.setTextCursor(cursor)


def test_a_gradient_clicked_with_words_picked_goes_on_just_them(window):
    from core import gradient_presets as gp

    item = window._item
    _select_in_box(window, 6, 9)
    before = window._stack.count()
    window.gradients_panel.choose(gp.Gradient("t", "#ff0000", "#0000ff"))
    assert [r[:4] for r in item.range_gradients] == [(6, 9, "#ffff0000", "#ff0000ff")]
    assert not item.gradient_enabled, "the rest of the text is left alone"
    assert window._stack.count() == before + 1
    window._stack.undo()
    assert item.range_gradients == ()
    window._stack.redo()
    assert [r[:2] for r in item.range_gradients] == [(6, 9)]


def test_with_nothing_picked_the_whole_text_still_fades(window):
    from core import gradient_presets as gp

    item = window._item
    window.gradients_panel.choose(gp.Gradient("t", "#ff0000", "#0000ff"))
    assert item.gradient_enabled and item.range_gradients == ()


def test_the_words_stay_picked_for_the_next_change(window):
    _select_in_box(window, 0, 5)
    window.bold_button.click()
    assert window.text_ctrl.panel_selection() == (0, 5), "pick once, change several things"


def test_the_layer_style_gradient_switch_works_on_picked_words(window):
    item = window._item
    _select_in_box(window, 0, 5)
    window.gradient_color_button.setProperty("selected_color", "#00aa00")
    window.gradient_checkbox.setChecked(True)
    window.text_ctrl.apply_gradient_settings()
    assert [r[:2] for r in item.range_gradients] == [(0, 5)]
    assert item.range_gradients[0][3] == "#ff00aa00"
    assert not item.gradient_enabled
    window.gradient_checkbox.setChecked(False)
    window.text_ctrl.apply_gradient_settings()
    assert item.range_gradients == ()
