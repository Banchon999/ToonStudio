"""The Model field of a provider's settings section (modules/utils/llm_providers).

Presents itself as a line edit — `text()`, `setText()`, `textChanged` — like
the OpenRouter picker, so the settings page saves and loads it with the rest.
It lists the provider's suggested models; "Refresh list" asks the provider
which models this key can use. Empty means the provider's default.
"""

from __future__ import annotations

import threading

from PySide6 import QtCore, QtWidgets

from modules.utils.llm_providers import Provider, list_models

from ..dayu_widgets.label import MLabel
from ..dayu_widgets.push_button import MPushButton
from .utils import set_label_width


class ProviderModelField(QtWidgets.QWidget):
    textChanged = QtCore.Signal(str)
    # Emitted from the fetch thread; Qt queues it onto the GUI thread.
    _fetched = QtCore.Signal(object, str)

    INPUT_WIDTH = 400

    def __init__(self, prov: Provider, api_key_source: QtWidgets.QLineEdit, parent=None):
        super().__init__(parent)
        self.provider = prov
        self._api_key_source = api_key_source
        self._fetching = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        prefix = MLabel(self.tr("Model")).border()
        set_label_width(prefix)
        prefix.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        row.addWidget(prefix)

        self.combo = QtWidgets.QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.combo.setFixedWidth(max(160, self.INPUT_WIDTH - prefix.maximumWidth() - row.spacing()))
        self.combo.setMaxVisibleItems(14)
        self.combo.addItems(prov.models)
        self.combo.setEditText("")
        self.combo.lineEdit().setPlaceholderText(
            self.tr("Default: {0}").format(prov.default_model))
        completer = QtWidgets.QCompleter(self.combo.model(), self.combo)
        completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        self.combo.setCompleter(completer)
        row.addWidget(self.combo)
        row.addStretch(1)
        layout.addLayout(row)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(8)
        self.refresh_button = MPushButton(self.tr("Refresh list")).small()
        self.refresh_button.setToolTip(self.tr("Ask {0} which models this key can use.").format(prov.company))
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        self.status_label = MLabel("").secondary()
        controls.addWidget(self.status_label)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.combo.currentTextChanged.connect(self._emit_text)
        self._fetched.connect(self._on_fetched)

    # Line-edit interface

    def text(self) -> str:
        return self.combo.currentText().strip()

    def setText(self, value: str) -> None:
        value = (value or "").strip()
        if self.combo.currentText() != value:
            self.combo.setEditText(value)

    def _emit_text(self, _text: str = "") -> None:
        self.textChanged.emit(self.text())

    # Model list

    def refresh(self) -> None:
        if self._fetching:
            return
        self._fetching = True
        self.refresh_button.setEnabled(False)
        self.status_label.setText(self.tr("Loading models…"))
        key = self._api_key_source.text()
        prov = self.provider

        # A plain thread that only emits this widget's signal: a QObject made
        # on a worker and destroyed there can deadlock PySide (see CLAUDE.md).
        def work():
            try:
                result = list_models(prov, key), ""
            except Exception as exc:  # network, refused key, odd payload
                result = None, str(exc)
            try:
                self._fetched.emit(*result)
            except RuntimeError:
                pass  # the settings window closed while it ran

        threading.Thread(target=work, daemon=True).start()

    def _on_fetched(self, models, error: str) -> None:
        self._fetching = False
        self.refresh_button.setEnabled(True)
        if models is None:
            self.status_label.setText(self.tr("Could not load the list: {0}").format(error[:120]))
            return
        current = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(models or list(self.provider.models))
        self.combo.setEditText(current)
        self.combo.blockSignals(False)
        self.status_label.setText(self.tr("{0} models").format(len(models)))
