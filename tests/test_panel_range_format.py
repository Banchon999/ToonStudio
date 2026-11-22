"""Formatting part of a text from the translation box on the right.

Select words in the box, pick a font (size, colour, bold, outline…), and only
those words change on the canvas — the owner's request, since selecting on
the canvas means double-clicking into a small box first.
"""

import numpy as np
import pytest
from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTextCursor


@pytest.fixture
def window(qapp):
    import controller

    win = controller.ComicTranslate()
    win.image_viewer.display_image_array(np.full((300, 600, 3), 230, dtype=np.uint8))
    stack = QtGui.QUndoStack()
    win.undo_group.addStack(stack)
    win.undo_group.setActiveStack(stack)
    win._test_stack = stack
    yield win
    win._skip_close_prompt = True
    win.close()


def _typed_item(win, text="HELLO WORLD"):
    viewer = win.image_viewer
    win.type_text_button.setChecked(True)
    win.toggle_type_text_tool()
    viewer.add_text_requested.emit(QPointF(40, 60))
    item = viewer.text_items[-1]
    item.textCursor().insertText(text)
    win.text_ctrl._commit_pending_text_command()
    item.exit_editing_mode() if hasattr(item, "exit_editing_mode") else None
    c = item.textCursor()
    c.clearSelection()
    item.setTextCursor(c)
    win.text_ctrl.on_text_item_selected(item)
    QtWidgets.QApplication.processEvents()
    assert win.t_text_edit.toPlainText() == text
    return item


def _select_in_box(win, start, end):
    c = win.t_text_edit.textCursor()
    c.setPosition(start)
    c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    win.t_text_edit.setTextCursor(c)


def _families(item):
    out, block = [], item.document().begin()
    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        out.append((frag.text(), frag.charFormat().font().family()))
        it += 1
    return out


def test_a_font_picked_with_words_selected_in_the_box_changes_only_them(window):
    item = _typed_item(window)
    before = item.document().defaultFont().family()
    _select_in_box(window, 6, 11)
    window.font_dropdown.setCurrentText("DejaVu Serif")
    frags = dict(_families(item))
    assert frags["WORLD"] == "DejaVu Serif"
    assert frags["HELLO "] != "DejaVu Serif"
    assert not item.textCursor().hasSelection(), "the item's own cursor is left as it was"
    assert item.document().defaultFont().family() == before, "the item's font is not changed"

    window._test_stack.undo()
    assert all(fam != "DejaVu Serif" for _, fam in _families(item))


def test_bold_and_colour_follow_the_box_selection_too(window):
    item = _typed_item(window)
    _select_in_box(window, 0, 5)
    window.bold_button.setChecked(True)
    window.text_ctrl.bold()
    weights = {}
    it = item.document().begin().begin()
    while not it.atEnd():
        frag = it.fragment()
        weights[frag.text()] = frag.charFormat().fontWeight()
        it += 1
    assert weights["HELLO"] >= QtGui.QFont.Weight.Bold
    assert weights[" WORLD"] < QtGui.QFont.Weight.Bold


def test_without_a_box_selection_the_whole_item_changes(window):
    item = _typed_item(window)
    window.font_dropdown.setCurrentText("DejaVu Serif")
    assert {fam for _, fam in _families(item)} == {"DejaVu Serif"}


def test_a_box_that_no_longer_matches_the_item_stands_for_nothing(window):
    item = _typed_item(window)
    window.t_text_edit.blockSignals(True)
    window.t_text_edit.setPlainText("something else entirely")
    window.t_text_edit.blockSignals(False)
    _select_in_box(window, 0, 4)
    assert window.text_ctrl.panel_selection() is None
    window.font_dropdown.setCurrentText("DejaVu Serif")
    assert {fam for _, fam in _families(item)} == {"DejaVu Serif"}
