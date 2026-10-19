"""Choose the Smart Workflow steps and their order."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.controllers.smart_workflow import load_order, save_order, step_label
from app.ui.dayu_widgets.label import MLabel
from app.ui.dayu_widgets.push_button import MPushButton
from core.smart_workflow import DEFAULT_ORDER, validate

STEP_ROLE = QtCore.Qt.ItemDataRole.UserRole


class SmartWorkflowDialog(QtWidgets.QDialog):
    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.main = main
        self.setWindowTitle(self.tr("Smart Workflow"))
        self.setMinimumWidth(420)

        intro = MLabel(self.tr(
            "Each step runs on every page before the next one starts. Drag to change "
            "the order, untick to leave a step out. A page that already has a step's "
            "result is skipped for that step, so your edits are kept.")).secondary()
        intro.setWordWrap(True)

        self.steps = QtWidgets.QListWidget()
        self.steps.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.steps.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.steps.model().rowsMoved.connect(self._check)
        self.steps.itemChanged.connect(self._check)

        self.problems = MLabel()
        self.problems.setWordWrap(True)

        reset = MPushButton(self.tr("Reset to default"))
        reset.clicked.connect(lambda: self._fill([(s, True) for s in DEFAULT_ORDER]))
        self.save_button = MPushButton(self.tr("Save"))
        self.run_button = MPushButton(self.tr("Save and Run")).primary()
        cancel = MPushButton(self.tr("Cancel"))
        self.save_button.clicked.connect(self._save)
        self.run_button.clicked.connect(self._save_and_run)
        cancel.clicked.connect(self.reject)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.run_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.steps, 1)
        layout.addWidget(self.problems)
        layout.addLayout(buttons)
        self._fill(load_order())

    def _fill(self, order):
        self.steps.blockSignals(True)
        self.steps.clear()
        for step, enabled in order:
            item = QtWidgets.QListWidgetItem(step_label(step))
            item.setData(STEP_ROLE, step)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable
                          | QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsDropEnabled)
            item.setCheckState(QtCore.Qt.CheckState.Checked if enabled else QtCore.Qt.CheckState.Unchecked)
            self.steps.addItem(item)
        self.steps.blockSignals(False)
        self._check()

    def order(self) -> list[tuple[str, bool]]:
        return [
            (self.steps.item(i).data(STEP_ROLE),
             self.steps.item(i).checkState() == QtCore.Qt.CheckState.Checked)
            for i in range(self.steps.count())
        ]

    def _check(self, *_):
        enabled = [s for s, on in self.order() if on]
        problems = validate(enabled)
        blocking = [p for p in problems if p.blocking]
        messages = []
        for p in problems:
            if p.step == "render" and not p.blocking:
                messages.append(self.tr("Render comes before Clean: the translation is drawn over the original text."))
            elif p.blocking and p.step:
                from core.smart_workflow import REQUIRES
                messages.append(self.tr("{0} must come after {1}.").format(
                    step_label(p.step), step_label(REQUIRES.get(p.step, ""))))
            else:
                messages.append(p.message)
        if not enabled:
            messages.append(self.tr("Switch on at least one step."))
        self.problems.setText("\n".join(messages))
        ok = not blocking and bool(enabled)
        self.save_button.setEnabled(ok)
        self.run_button.setEnabled(ok and not self.main.smart_ctrl.running)

    def _save(self):
        save_order(self.order())
        self.accept()

    def _save_and_run(self):
        save_order(self.order())
        self.accept()
        self.main.smart_radio.setChecked(True)
        self.main.smart_mode_selected()
        self.main.smart_ctrl.start()
