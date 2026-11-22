"""Outline presets: a text's edge (outline + extra strokes) in one pick."""

import numpy as np
import pytest
from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTextCursor

from modules.utils.outline_presets import BUILT_IN, OutlinePreset, OutlinePresetStore


def test_built_ins_are_read_only_and_user_presets_persist(tmp_path):
    path = str(tmp_path / "outline.json")
    store = OutlinePresetStore(path)
    assert [p.name for p in store.all()][: len(BUILT_IN)] == [p.name for p in BUILT_IN]
    with pytest.raises(ValueError):
        store.put(OutlinePreset("thin BLACK", "#ff0000", 2))
    store.put(OutlinePreset("Group SFX", "#ff0000", 4, [("#000000", 2)]))
    again = OutlinePresetStore(path)
    mine = again.get("Group SFX")
    assert mine is not None and not mine.builtin and mine.strokes == [("#000000", 2.0)]
    assert again.remove("Group SFX") and OutlinePresetStore(path).get("Group SFX") is None
    assert not again.remove("Thin black")


def test_a_broken_file_reads_as_no_user_presets(tmp_path):
    path = tmp_path / "outline.json"
    path.write_text("{not json")
    assert len(OutlinePresetStore(str(path)).all()) == len(BUILT_IN)


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    import controller
    from modules.utils import outline_presets

    monkeypatch.setattr(outline_presets, "get_user_data_dir", lambda *a: str(tmp_path))
    win = controller.ComicTranslate()
    win.image_viewer.display_image_array(np.full((300, 600, 3), 230, dtype=np.uint8))
    stack = QtGui.QUndoStack()
    win.undo_group.addStack(stack)
    win.undo_group.setActiveStack(stack)
    win._test_stack = stack
    win.type_text_button.setChecked(True)
    win.toggle_type_text_tool()
    win.image_viewer.add_text_requested.emit(QPointF(40, 60))
    item = win.image_viewer.text_items[-1]
    item.textCursor().insertText("HELLO WORLD")
    win.text_ctrl._commit_pending_text_command()
    c = item.textCursor()
    c.clearSelection()
    item.setTextCursor(c)
    win.text_ctrl.on_text_item_selected(item)
    win._item = item
    QtWidgets.QApplication.processEvents()
    yield win
    win._skip_close_prompt = True
    win.close()


def _pick(win, name):
    combo = win.outline_preset_combo
    combo.setCurrentIndex(combo.findData(name))
    win.text_ctrl.apply_outline_preset()


def test_the_panel_lists_every_preset(window):
    names = [window.outline_preset_combo.itemData(i) for i in range(window.outline_preset_combo.count())]
    assert names[0] == "" and names[1:] == [p.name for p in BUILT_IN]


def test_a_preset_sets_outline_and_strokes_in_one_undo_step(window):
    item = window._item
    _pick(window, "White, black edge")
    assert item.outline and QtGui.QColor(item.outline_color).name() == "#ffffff"
    assert item.outline_width == 2.5
    assert [(layer.color.lower()[-6:], layer.width) for layer in item.stroke_layers] == [("000000", 2.0)]
    assert window.outline_checkbox.isChecked() and window.outline_width_dropdown.currentText() == "2.5"
    window._test_stack.undo()
    assert item.stroke_layers == []


def test_with_words_selected_only_their_outline_changes(window):
    item = window._item
    c = window.t_text_edit.textCursor()
    c.setPosition(0)
    c.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
    window.t_text_edit.setTextCursor(c)
    _pick(window, "Thick black")
    ranges = [(o.start, o.end, o.width) for o in item.selection_outlines]
    assert (0, 5, 3.0) in ranges
    assert item.stroke_layers == [], "strokes are item-wide, so a few words do not get them"


def test_the_selected_texts_outline_can_be_saved(window, monkeypatch):
    item = window._item
    item.set_outline(QtGui.QColor("#ff0000"), 4.0)
    item.set_stroke_layers([("#00ff00", 2.0)])
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *a, **k: ("Red SFX", True))
    window.text_ctrl.save_outline_preset()
    saved = window.text_ctrl.outline_preset_store.get("Red SFX")
    assert saved.color == "#ff0000" and saved.width == 4.0 and saved.strokes[0][1] == 2.0
    assert window.outline_preset_combo.currentData() == "Red SFX"
