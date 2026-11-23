from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QSettings

from app.shortcuts import (
    TOOL_GROUPS,
    brush_size_step,
    get_default_shortcuts,
    get_shortcut_definitions,
    next_tool,
)

if TYPE_CHECKING:
    from controller import ComicTranslate


class ShortcutController:
    SETTINGS_GROUP = "shortcuts"

    def __init__(self, main: "ComicTranslate"):
        self.main = main
        self._shortcuts: dict[str, QtGui.QShortcut] = {}
        self._cycle_shortcuts: dict[str, QtGui.QShortcut] = {}
        self._register_shortcuts()

    def _register_shortcuts(self) -> None:
        for definition in get_shortcut_definitions():
            shortcut = QtGui.QShortcut(self.main)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(
                lambda shortcut_id=definition.id: self._activate_shortcut(shortcut_id)
            )
            self._shortcuts[definition.id] = shortcut
            if definition.id in TOOL_GROUPS and len(TOOL_GROUPS[definition.id]) > 1:
                # Shift + the group's key steps through the group, as in Photoshop.
                cycle = QtGui.QShortcut(self.main)
                cycle.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
                cycle.activated.connect(
                    lambda shortcut_id=definition.id: self._activate_tool_group(shortcut_id, cycle=True)
                )
                self._cycle_shortcuts[definition.id] = cycle

        self.apply_shortcuts()

    def apply_shortcuts(self) -> None:
        current_shortcuts = self.get_current_shortcuts()
        for shortcut_id, shortcut in self._shortcuts.items():
            shortcut.setKey(QtGui.QKeySequence(current_shortcuts.get(shortcut_id, "")))
        for shortcut_id, shortcut in self._cycle_shortcuts.items():
            shortcut.setKey(self._shifted(current_shortcuts.get(shortcut_id, "")))

    @staticmethod
    def _shifted(sequence: str) -> QtGui.QKeySequence:
        """Shift + a single plain key; nothing when the key already has a modifier."""
        keys = QtGui.QKeySequence(sequence)
        if keys.count() != 1:
            return QtGui.QKeySequence()
        combo = keys[0]
        if combo.keyboardModifiers() != QtCore.Qt.KeyboardModifier.NoModifier:
            return QtGui.QKeySequence()
        return QtGui.QKeySequence(QtCore.QKeyCombination(QtCore.Qt.KeyboardModifier.ShiftModifier, combo.key()))

    def get_current_shortcuts(self) -> dict[str, str]:
        shortcuts = get_default_shortcuts()
        settings = QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup(self.SETTINGS_GROUP)
        for definition in get_shortcut_definitions():
            shortcuts[definition.id] = settings.value(
                definition.id,
                shortcuts[definition.id],
                type=str,
            )
        settings.endGroup()
        return shortcuts

    def _activate_shortcut(self, shortcut_id: str) -> None:
        handlers = {
            "save_project": self._save_project,
            "save_current_image": self._save_current_image,
            "undo": self._undo,
            "redo": self._redo,
            "delete_selected_box": self._delete_selected_box,
            "restore_text_blocks": self._restore_text_blocks,
            "toggle_brush_strokes": self._toggle_brush_strokes,
            "select_all": lambda: self._selection("select_all"),
            "deselect": lambda: self._selection("deselect"),
            "invert_selection": lambda: self._selection("invert"),
        }
        if shortcut_id in TOOL_GROUPS:
            self._activate_tool_group(shortcut_id, cycle=False)
            return
        if shortcut_id in ("brush_smaller", "brush_larger"):
            self._step_brush_size(shortcut_id == "brush_larger")
            return
        handler = handlers.get(shortcut_id)
        if handler is not None:
            handler()

    def _tool_keys_allowed(self) -> bool:
        """Single-letter keys belong to whatever is being typed into."""
        return (
            self._workspace_is_active()
            and not self._is_text_input_focused()
            and not self._canvas_text_is_being_edited()
        )

    def _activate_tool_group(self, group_id: str, cycle: bool) -> None:
        if not self._tool_keys_allowed():
            return
        group = tuple(t for t in TOOL_GROUPS[group_id] if t in self.main.tool_buttons)
        if not group:
            return
        tool = next_tool(group, self.main.image_viewer.current_tool, cycle)
        button = self.main.tool_buttons[tool]
        if button.isEnabled() and not button.isChecked():
            button.click()

    def _step_brush_size(self, larger: bool) -> None:
        if not self._tool_keys_allowed():
            return
        slider = self.main.brush_eraser_slider
        value = brush_size_step(slider.value(), larger)
        slider.setValue(max(slider.minimum(), min(slider.maximum(), value)))

    def _workspace_is_active(self) -> bool:
        try:
            return self.main._center_stack.currentWidget() is self.main.main_content_widget
        except Exception:
            return False

    def _is_text_input_focused(self) -> bool:
        focus_widget = QtWidgets.QApplication.focusWidget()
        editable_types = (
            QtWidgets.QLineEdit,
            QtWidgets.QTextEdit,
            QtWidgets.QPlainTextEdit,
            QtWidgets.QAbstractSpinBox,
            QtWidgets.QKeySequenceEdit,
        )
        return isinstance(focus_widget, editable_types)

    def _undo(self) -> None:
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        stack = self.main.undo_group.activeStack()
        if stack is not None and stack.canUndo():
            self.main.undo_group.undo()

    def _save_project(self) -> None:
        if not self._workspace_is_active():
            return
        self.main.project_ctrl.thread_save_project()

    def _save_current_image(self) -> None:
        if not self._workspace_is_active():
            return
        self.main.save_browser.click()

    def _redo(self) -> None:
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        stack = self.main.undo_group.activeStack()
        if stack is not None and stack.canRedo():
            self.main.undo_group.redo()

    def _delete_selected_box(self) -> None:
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        self.main.delete_selected_box()

    def _restore_text_blocks(self) -> None:
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        self.main.restore_text_blocks()

    def _toggle_brush_strokes(self) -> None:
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        self.main.brush_button.click()

    def _selection(self, action: str) -> None:
        # Ctrl+A in a text field, or while typing into a text box on the
        # canvas, selects text — not the page.
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        if self._canvas_text_is_being_edited():
            return
        getattr(self.main.selection_ctrl, action)()

    def _canvas_text_is_being_edited(self) -> bool:
        # Not scene.focusItem(): a scene whose view is inactive reports no focus
        # item even while a text box is open for typing.
        from app.ui.canvas.text_item import TextBlockItem

        return any(
            isinstance(item, TextBlockItem) and item.editing_mode
            for item in self.main.image_viewer.scene().items()
        )
