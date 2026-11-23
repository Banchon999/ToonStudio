"""The font menu (Photoshop's/PhotoCraft's) and font changes on selected layers only."""

import numpy as np
import pytest
from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QPointF

from core import font_class as fc

NONE = (0,) * 10


class TestClassify:
    """Ported from PhotoCraft's own tests for the same rules."""

    def test_the_os2_class_wins_over_the_name(self):
        assert fc.classify("Georgia", 0x0105, NONE, False) == fc.SERIF
        assert fc.classify("Georgia", 0x0405, NONE, False) == fc.SERIF
        assert fc.classify("Rockwell", 0x0501, NONE, False) == fc.SLAB_SERIF
        assert fc.classify("Arial", 0x0805, NONE, False) == fc.SANS_SERIF
        assert fc.classify("Edwardian Script ITC", 0x0A05, NONE, False) == fc.SCRIPT
        assert fc.classify("Wingdings", 0x0C00, NONE, False) == fc.DECORATIVE

    def test_panose_classifies_fonts_without_an_os2_class(self):
        assert fc.classify("A", 0, (2, 11, 6, 4, 2, 2, 2, 2, 2, 4), False) == fc.SANS_SERIF
        assert fc.classify("B", 0, (2, 6, 6, 3, 2, 2, 2, 2, 2, 4), False) == fc.SLAB_SERIF
        assert fc.classify("C", 0, (2, 2, 6, 3, 5, 4, 5, 2, 3, 4), False) == fc.SERIF
        assert fc.classify("D", 0, (3, 1, 1, 1, 1, 1, 1, 1, 1, 1), False) == fc.HANDWRITTEN
        assert fc.classify("E", 0, (4, 1, 1, 1, 1, 1, 1, 1, 1, 1), False) == fc.DECORATIVE
        assert fc.classify("F", 0, (2, 11, 6, 9, 2, 2, 2, 2, 2, 4), False) == fc.MONOSPACE

    def test_fixed_pitch_and_names_decide_the_rest(self):
        assert fc.classify("Anything", 0x0805, NONE, True) == fc.MONOSPACE
        assert fc.classify("UnifrakturMaguntia", 0, NONE, False) == fc.BLACKLETTER
        assert fc.classify("Roboto Slab", 0, NONE, False) == fc.SLAB_SERIF
        assert fc.classify("Noto Sans", 0, NONE, False) == fc.SANS_SERIF
        assert fc.classify("Fira Code", 0, NONE, False) == fc.MONOSPACE
        assert fc.classify("Encode Sans", 0, NONE, False) == fc.SANS_SERIF, "'code' inside a word"
        assert fc.classify("Permanent Marker", 0, NONE, False) == fc.HANDWRITTEN
        assert fc.classify("LilyUPC", 0, NONE, False) is None, "a Thai face that says nothing"

    def test_tables_are_read_from_their_bytes(self):
        os2 = bytearray(96)
        os2[30:32] = (0x08, 0x05)
        os2[32:42] = bytes((2, 11, 6, 4, 2, 2, 2, 2, 2, 4))
        post = bytearray(32)
        post[12:16] = (0, 0, 0, 1)
        assert fc.parse_tables(bytes(os2), bytes(post)) == (0x0805, (2, 11, 6, 4, 2, 2, 2, 2, 2, 4), True)
        assert fc.parse_tables(b"", b"") == (0, NONE, False)

    def test_search_wants_every_word(self):
        assert fc.matches("plex thai", "IBM Plex Sans Thai")
        assert not fc.matches("plex mono", "IBM Plex Sans Thai")


@pytest.fixture
def win(qapp):
    import controller

    window = controller.ComicTranslate()
    window.image_viewer.display_image_array(np.full((400, 600, 3), 230, dtype=np.uint8))
    stack = QtGui.QUndoStack()
    window.undo_group.addStack(stack)
    window.undo_group.setActiveStack(stack)
    window._stack = stack
    window.type_text_button.setChecked(True)
    window.toggle_type_text_tool()
    items = []
    for i, text in enumerate(("ONE", "TWO", "THREE")):
        window.image_viewer.add_text_requested.emit(QPointF(40, 40 + i * 100))
        item = window.image_viewer.text_items[-1]
        item.textCursor().insertText(text)
        window.text_ctrl._commit_pending_text_command()
        cursor = item.textCursor()
        cursor.clearSelection()
        item.setTextCursor(cursor)
        items.append(item)
    window.set_tool(None)
    window._items = items
    yield window
    window._skip_close_prompt = True
    window.close()


def _families(item):
    out, it = set(), item.document().begin().begin()
    while not it.atEnd():
        out.add(it.fragment().charFormat().font().family())
        it += 1
    return out


def test_the_menu_filters_by_class_search_and_favourites(win, qapp):
    from app.ui.font_favourites import favourites

    win.text_ctrl.on_text_item_selected(win._items[0])
    win.font_dropdown.showPopup()
    picker = win.font_dropdown.picker
    every = picker.font_list.topLevelItemCount()
    assert every >= 3
    picker.search.setText("dejavu")
    names = [picker.font_list.topLevelItem(i).text(1) for i in range(picker.font_list.topLevelItemCount())]
    assert names and all("dejavu" in n.lower() for n in names)
    picker.clear_filters()
    assert picker.font_list.topLevelItemCount() == every
    picker.class_list.setCurrentRow(next(i for i in range(picker.class_list.count())
                                         if picker.class_list.item(i).data(0x0100) == fc.MONOSPACE))
    mono = [picker.font_list.topLevelItem(i).text(1) for i in range(picker.font_list.topLevelItemCount())]
    assert "DejaVu Sans Mono" in mono and "DejaVu Sans" not in mono
    picker.clear_filters()
    row = picker.font_list.topLevelItem(0)
    name = row.text(1)
    picker._on_item_clicked(row, 0)  # the star
    assert favourites().is_favourite(name)
    picker.favourites_only.setChecked(True)  # refills the list
    assert [picker.font_list.topLevelItem(i).text(1)
            for i in range(picker.font_list.topLevelItemCount())] == [name]
    favourites().toggle(name)
    picker.close()


def test_the_preview_shows_the_selected_text(win):
    win.text_ctrl.on_text_item_selected(win._items[1])
    win.font_dropdown.showPopup()
    picker = win.font_dropdown.picker
    picker._show_preview("DejaVu Serif")
    assert picker.preview.text().startswith("TWO")
    assert picker.preview_name.text() == "DejaVu Serif"
    picker.close()


def test_picking_a_font_changes_the_selected_layers_only(win, qapp):
    one, two, three = win._items
    for item in win.image_viewer.text_items:
        item.selected = False
        item.setSelected(False)
    win.layers_panel.setVisible(True)
    win.layers_panel.rebuild()
    from app.ui.layers_panel import COL_NAME, ROLE_OBJECT

    tree = win.layers_panel.tree
    rows = [tree.topLevelItem(0).child(i) for i in range(tree.topLevelItem(0).childCount())]
    for row in rows:
        if row.data(COL_NAME, ROLE_OBJECT) in (one.object_id, two.object_id):
            row.setSelected(True)
    assert set(win.image_viewer.get_selected_text_items()) == {one, two}
    win.font_dropdown.showPopup()
    win.font_dropdown.picker._choose("DejaVu Serif")
    assert _families(one) == {"DejaVu Serif"} and _families(two) == {"DejaVu Serif"}
    assert "DejaVu Serif" not in _families(three)
    win._stack.undo()  # one step for both
    assert "DejaVu Serif" not in _families(one) | _families(two)
