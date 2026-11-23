"""Tool keys as in Photoshop: one letter per tool group, Shift + letter steps
through the group, [ and ] size the brush, Space held pans with any tool.

Letters must never be taken from something being typed into — a text field or
a text box on the canvas — or the letter would vanish from the text.
"""

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from app.shortcuts import TOOL_GROUPS, brush_size_step, get_default_shortcuts, next_tool


def test_a_group_key_keeps_the_tool_in_hand_and_shift_steps_through():
    group = ("spotheal", "aibrush", "heal")
    assert next_tool(group, None, cycle=False) == "spotheal"
    assert next_tool(group, "aibrush", cycle=False) == "aibrush"
    assert next_tool(group, "aibrush", cycle=True) == "heal"
    assert next_tool(group, "heal", cycle=True) == "spotheal"
    assert next_tool(group, "brush", cycle=True) == "spotheal"


def test_brush_size_steps_go_both_ways_and_never_below_one():
    assert brush_size_step(1, larger=False) == 1
    assert brush_size_step(5, larger=True) == 6
    assert brush_size_step(10, larger=False) == 9
    assert brush_size_step(60, larger=True) == 70
    assert brush_size_step(60, larger=False) == 50


def test_every_tool_group_has_a_distinct_default_key():
    defaults = get_default_shortcuts()
    keys = [defaults[g] for g in TOOL_GROUPS]
    assert all(keys) and len(set(keys)) == len(keys)
    assert len(set(defaults.values()) - {""}) == len([v for v in defaults.values() if v])


@pytest.fixture
def window(qapp):
    import controller

    win = controller.ComicTranslate()
    win.show_main_page() if hasattr(win, "show_main_page") else None
    win._center_stack.setCurrentWidget(win.main_content_widget)
    win.image_viewer.display_image_array(np.full((300, 400, 3), 220, dtype=np.uint8))
    stack = QtGui.QUndoStack()
    win.undo_group.addStack(stack)
    win.undo_group.setActiveStack(stack)
    win.show()
    win.activateWindow()
    win.image_viewer.setFocus()
    qapp.processEvents()
    yield win
    win._skip_close_prompt = True
    win.close()


def press(widget, key, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(widget, key, modifier)
    QtWidgets.QApplication.processEvents()


def test_letters_pick_tools_and_shift_cycles(window):
    viewer = window.image_viewer
    press(viewer, Qt.Key.Key_B)
    assert viewer.current_tool == "brush" and window.brush_button.isChecked()
    press(viewer, Qt.Key.Key_B, Qt.KeyboardModifier.ShiftModifier)
    assert viewer.current_tool == "paint" and not window.brush_button.isChecked()
    press(viewer, Qt.Key.Key_B)
    assert viewer.current_tool == "paint"  # the key keeps the group's tool in hand
    press(viewer, Qt.Key.Key_J)
    assert viewer.current_tool == "spotheal"
    press(viewer, Qt.Key.Key_W)
    assert viewer.current_tool == "wand"
    press(viewer, Qt.Key.Key_H)
    assert viewer.current_tool == "pan"


def test_brackets_resize_the_brush(window):
    viewer = window.image_viewer
    press(viewer, Qt.Key.Key_B)
    window.brush_eraser_slider.setValue(20)
    press(viewer, Qt.Key.Key_BracketRight)
    assert window.brush_eraser_slider.value() == 25
    press(viewer, Qt.Key.Key_BracketLeft)
    press(viewer, Qt.Key.Key_BracketLeft)
    assert window.brush_eraser_slider.value() == 15


def test_letters_typed_into_a_field_stay_text(window):
    field = window.s_text_edit
    field.setFocus()
    QtWidgets.QApplication.processEvents()
    tool = window.image_viewer.current_tool
    QTest.keyClicks(field, "bheg")
    QtWidgets.QApplication.processEvents()
    assert field.toPlainText().endswith("bheg")
    assert window.image_viewer.current_tool == tool


def test_letters_typed_into_a_canvas_text_box_stay_text(window):
    viewer = window.image_viewer
    window.type_text_button.setChecked(True)
    window.toggle_type_text_tool()
    viewer.add_text_requested.emit(QPointF(60, 60))
    item = viewer.text_items[-1]
    assert item.editing_mode
    viewer.setFocus()
    item.setFocus()
    QtWidgets.QApplication.processEvents()
    QTest.keyClicks(viewer, "bhs")
    QtWidgets.QApplication.processEvents()
    assert item.toPlainText().endswith("bhs")
    assert viewer.current_tool == "type"


def test_space_held_pans_and_release_gives_the_tool_back(window):
    viewer = window.image_viewer
    press(viewer, Qt.Key.Key_B)
    QTest.keyPress(viewer, Qt.Key.Key_Space)
    QtWidgets.QApplication.processEvents()
    assert viewer.space_panning
    assert viewer.dragMode() == QtWidgets.QGraphicsView.DragMode.ScrollHandDrag
    assert viewer.current_tool == "brush"
    QTest.keyRelease(viewer, Qt.Key.Key_Space)
    QtWidgets.QApplication.processEvents()
    assert not viewer.space_panning
    assert viewer.dragMode() == QtWidgets.QGraphicsView.DragMode.NoDrag
    assert viewer.current_tool == "brush"
