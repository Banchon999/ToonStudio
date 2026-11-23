"""The Character panel's glyph toggles and the Paragraph panel's fields.

All caps, small caps, superscript, subscript and strikethrough, Photoshop's
row of T buttons, apply to the selected words (in the translation box or on
the canvas) or to the whole text; justify and the indent/spacing fields to
the paragraphs. Each change is one undo step and survives a save (HTML),
and the Skia engine hands such text to Qt, which can draw it.
"""

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets
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
    c = item.textCursor()
    c.clearSelection()
    item.setTextCursor(c)
    win.text_ctrl.on_text_item_selected(item)
    QtWidgets.QApplication.processEvents()
    return item


def _select_in_box(win, start, end):
    c = win.t_text_edit.textCursor()
    c.setPosition(start)
    c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    win.t_text_edit.setTextCursor(c)


def _fragments(item):
    out, block = [], item.document().begin()
    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        out.append((frag.text(), frag.charFormat()))
        it += 1
    return out


def test_every_toggle_and_field_is_in_its_panel(window):
    assert set(window.char_style_buttons) == {"all_caps", "small_caps", "superscript", "subscript", "strikethrough"}
    assert set(window.paragraph_spins) == {"indent_left", "indent_right", "indent_first", "space_before", "space_after"}
    for button in window.char_style_buttons.values():
        assert window.character_panel.isAncestorOf(button)
    for spin in window.paragraph_spins.values():
        assert window.paragraph_panel.isAncestorOf(spin)
    assert len(window.alignment_tool_group.get_button_group().buttons()) == 4


def test_all_caps_on_words_selected_in_the_box_changes_only_them(window):
    item = _typed_item(window, "hello world")
    _select_in_box(window, 6, 11)
    window.char_style_buttons["all_caps"].click()
    frags = dict((t, f.fontCapitalization()) for t, f in _fragments(item))
    assert frags["world"] == QtGui.QFont.Capitalization.AllUppercase
    assert frags["hello "] == QtGui.QFont.Capitalization.MixedCase
    assert item.toPlainText() == "hello world", "the letters are not rewritten, only shown in capitals"

    window._test_stack.undo()
    assert all(f.fontCapitalization() == QtGui.QFont.Capitalization.MixedCase for _, f in _fragments(item))


def test_a_toggle_with_nothing_selected_changes_the_whole_text(window):
    item = _typed_item(window)
    window.char_style_buttons["strikethrough"].click()
    assert all(f.fontStrikeOut() for _, f in _fragments(item))
    assert item.char_styles()["strikethrough"]


def test_superscript_and_subscript_exclude_each_other(window):
    item = _typed_item(window)
    window.char_style_buttons["superscript"].click()
    window.char_style_buttons["subscript"].click()
    assert not window.char_style_buttons["superscript"].isChecked()
    styles = item.char_styles()
    assert styles["subscript"] and not styles["superscript"]


def test_justify_and_paragraph_fields(window):
    item = _typed_item(window)
    window.alignment_tool_group.get_button_group().buttons()[3].click()
    assert item.alignment == QtCore.Qt.AlignmentFlag.AlignJustify
    window.paragraph_spins["indent_left"].setValue(12)
    window.paragraph_spins["space_after"].setValue(6)
    fmt = item.document().begin().blockFormat()
    assert fmt.leftMargin() == 12 and fmt.bottomMargin() == 6
    assert fmt.alignment() & QtCore.Qt.AlignmentFlag.AlignJustify

    window._test_stack.undo()
    assert item.document().begin().blockFormat().bottomMargin() == 0
    assert item.document().begin().blockFormat().leftMargin() == 12


def test_the_panels_show_what_the_selected_item_has(window):
    item = _typed_item(window)
    item.set_char_style("small_caps", True)
    item.set_paragraph(indent_first=-8, space_before=4)
    edits = window._test_stack.count()
    window.text_ctrl.set_values_for_blk_item(item)
    assert window.char_style_buttons["small_caps"].isChecked()
    assert not window.char_style_buttons["all_caps"].isChecked()
    assert window.paragraph_spins["indent_first"].value() == -8
    assert window.paragraph_spins["space_before"].value() == 4
    # Showing them is not an edit.
    assert window._test_stack.count() == edits


def test_formats_survive_the_html_a_project_saves(qapp):
    from app.ui.canvas.text_item import TextBlockItem

    item = TextBlockItem(text="Hello world")
    for name in ("all_caps", "superscript", "strikethrough"):
        item.set_char_style(name, True)
    item.set_paragraph(indent_left=10, indent_right=5, indent_first=3, space_before=2, space_after=7)
    item.set_alignment(QtCore.Qt.AlignmentFlag.AlignJustify)

    copy = TextBlockItem(text="")
    copy.setHtml(item.toHtml())
    assert copy.char_styles() == item.char_styles()
    assert copy.paragraph() == item.paragraph()
    assert copy.document().begin().blockFormat().alignment() & QtCore.Qt.AlignmentFlag.AlignJustify


def test_skia_hands_such_text_to_qt(qapp):
    from app.ui.canvas import skia_paint
    from app.ui.canvas.text_item import TextBlockItem

    plain = TextBlockItem(text="Hello")
    capped = TextBlockItem(text="Hello")
    capped.set_char_style("all_caps", True)
    indented = TextBlockItem(text="Hello")
    indented.set_paragraph(indent_left=4)
    assert not skia_paint._needs_qt_layout(plain)
    assert skia_paint._needs_qt_layout(capped)
    assert skia_paint._needs_qt_layout(indented)
    assert not skia_paint.can_paint(capped)
    assert not skia_paint.can_paint(indented)
