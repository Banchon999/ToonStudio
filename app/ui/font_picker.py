"""The font menu, as in Photoshop and PhotoCraft.

Opened from the Character panel's font box (`PickerFontComboBox`): a preview
of the selected text in the font under the mouse, a filter bar (« to hide the
class list, ★ for favourites only, a search box, Clear All), the classes on
the left (`core/font_class.py`) and the families on the right with a star to
favour each. Picking a family sets the font box, which applies it to the
selected text layers only (`TextController.on_font_dropdown_change`).

A family's class is read from its own tables through QRawFont, once, on the
GUI thread (Qt's font database must not be touched from a worker); about
0.4 ms a family, and only when a class is chosen.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from core import font_class

from .dayu_widgets.combo_box import MFontComboBox

ROLE_FAMILY = QtCore.Qt.ItemDataRole.UserRole
_class_cache: dict[str, str | None] = {}


def class_of(family: str) -> str | None:
    """The family's class key (core.font_class), read once from its tables."""
    if family not in _class_cache:
        try:
            raw = QtGui.QRawFont.fromFont(QtGui.QFont(family))
            parsed = font_class.parse_tables(bytes(raw.fontTable("OS/2")), bytes(raw.fontTable("post")))
        except Exception:  # noqa: BLE001 — an unreadable font is unclassified, not an error
            parsed = (0, (0,) * 10, False)
        _class_cache[family] = font_class.classify(family, *parsed)
    return _class_cache[family]


class FontPickerPopup(QtWidgets.QFrame):
    chosen = QtCore.Signal(str)

    SAMPLE = "Aa กขค สวัสดี"

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Popup)
        self.setObjectName("toonFontPicker")
        # A top-level popup draws its stylesheet background only when asked to.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.resize(420, 460)
        self._sample = self.SAMPLE
        self._current = ""

        self.preview_name = QtWidgets.QLabel()
        self.preview_name.setObjectName("toonFontPickerName")
        self.preview = QtWidgets.QLabel()
        self.preview.setObjectName("toonFontPickerPreview")
        self.preview.setMinimumHeight(44)
        self.preview.setTextFormat(QtCore.Qt.TextFormat.PlainText)

        self.classes_toggle = QtWidgets.QToolButton()
        self.classes_toggle.setText("«")
        self.classes_toggle.setCheckable(True)
        self.classes_toggle.setToolTip(self.tr("Hide or show the font classes"))
        self.favourites_only = QtWidgets.QToolButton()
        self.favourites_only.setText("★")
        self.favourites_only.setCheckable(True)
        self.favourites_only.setToolTip(self.tr("Show favourite fonts only"))
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(self.tr("Search fonts"))
        self.search.setClearButtonEnabled(True)
        self.clear_button = QtWidgets.QPushButton(self.tr("Clear All"))
        self.clear_button.setFlat(True)

        self.class_list = QtWidgets.QListWidget()
        self.class_list.setObjectName("toonFontPickerClasses")
        self.class_list.setFixedWidth(128)
        all_item = QtWidgets.QListWidgetItem(self.tr("All Classes"))
        all_item.setData(ROLE_FAMILY, "")
        self.class_list.addItem(all_item)
        labels = {
            font_class.SERIF: self.tr("Serif"), font_class.SLAB_SERIF: self.tr("Slab Serif"),
            font_class.SANS_SERIF: self.tr("Sans Serif"), font_class.SCRIPT: self.tr("Script"),
            font_class.MONOSPACE: self.tr("Monospace"), font_class.HANDWRITTEN: self.tr("Handwritten"),
            font_class.BLACKLETTER: self.tr("Blackletter"), font_class.DECORATIVE: self.tr("Decorative"),
        }
        for key, _english in font_class.CLASSES:
            item = QtWidgets.QListWidgetItem(labels[key])
            item.setData(ROLE_FAMILY, key)
            self.class_list.addItem(item)
        self.class_list.setCurrentRow(0)

        self.font_list = QtWidgets.QTreeWidget()
        self.font_list.setObjectName("toonFontPickerList")
        self.font_list.setColumnCount(2)
        self.font_list.setHeaderHidden(True)
        self.font_list.setRootIsDecorated(False)
        self.font_list.setUniformRowHeights(True)
        self.font_list.setMouseTracking(True)
        self.font_list.header().setStretchLastSection(True)
        self.font_list.setColumnWidth(0, 26)

        filters = QtWidgets.QHBoxLayout()
        filters.addWidget(self.classes_toggle)
        filters.addWidget(self.favourites_only)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.clear_button)
        lists = QtWidgets.QHBoxLayout()
        lists.addWidget(self.class_list)
        lists.addWidget(self.font_list, 1)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.preview_name)
        layout.addWidget(self.preview)
        layout.addLayout(filters)
        layout.addLayout(lists, 1)

        self.classes_toggle.toggled.connect(self._toggle_classes)
        self.favourites_only.toggled.connect(self.refill)
        self.search.textChanged.connect(self.refill)
        self.class_list.currentRowChanged.connect(self.refill)
        self.clear_button.clicked.connect(self.clear_filters)
        self.font_list.itemEntered.connect(lambda item, _col: self._show_preview(item.data(1, ROLE_FAMILY)))
        self.font_list.currentItemChanged.connect(
            lambda item, _prev: item is not None and self._show_preview(item.data(1, ROLE_FAMILY))
        )
        self.font_list.itemClicked.connect(self._on_item_clicked)
        self.font_list.itemActivated.connect(lambda item, _col: self._choose(item.data(1, ROLE_FAMILY)))

    # --- filling ------------------------------------------------------------

    def _favourites(self):
        from app.ui.font_favourites import favourites

        return favourites()

    def families(self) -> list[str]:
        """The families the filters let through, in Qt's order."""
        families = list(QtGui.QFontDatabase.families())
        query = self.search.text().strip()
        if query:
            families = [f for f in families if font_class.matches(query, f)]
        if self.favourites_only.isChecked():
            favourites = self._favourites()
            families = [f for f in families if favourites.is_favourite(f)]
        item = self.class_list.currentItem()
        wanted = item.data(ROLE_FAMILY) if item is not None else ""
        if wanted:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            try:
                families = [f for f in families if class_of(f) == wanted]
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
        return families

    def refill(self, *_args) -> None:
        favourites = self._favourites()
        self.font_list.clear()
        current_row = None
        for family in self.families():
            row = QtWidgets.QTreeWidgetItem(self.font_list)
            self._paint_star(row, favourites.is_favourite(family))
            row.setToolTip(0, self.tr("Add to or remove from favourites"))
            row.setText(1, family)
            row.setData(1, ROLE_FAMILY, family)
            if family == self._current:
                current_row = row
        if current_row is not None:
            self.font_list.setCurrentItem(current_row)
            self.font_list.scrollToItem(current_row, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)
        self.clear_button.setEnabled(self._filtering())

    @staticmethod
    def _paint_star(row, favourite: bool) -> None:
        from core import theme_tokens
        from app.ui.dayu_widgets import dayu_theme

        tokens = getattr(dayu_theme, "tokens", None) or theme_tokens.DARK
        row.setText(0, "★" if favourite else "☆")
        row.setForeground(0, QtGui.QBrush(QtGui.QColor(tokens["accent"] if favourite else tokens["text_3"])))

    def _filtering(self) -> bool:
        return bool(self.search.text().strip()) or self.favourites_only.isChecked() or self.class_list.currentRow() > 0

    def clear_filters(self) -> None:
        for widget in (self.search, self.favourites_only, self.class_list):
            widget.blockSignals(True)
        self.search.clear()
        self.favourites_only.setChecked(False)
        self.class_list.setCurrentRow(0)
        for widget in (self.search, self.favourites_only, self.class_list):
            widget.blockSignals(False)
        self.refill()

    def _toggle_classes(self, hidden: bool) -> None:
        self.class_list.setVisible(not hidden)
        self.classes_toggle.setText("»" if hidden else "«")

    # --- preview and choosing -------------------------------------------------

    def _show_preview(self, family: str) -> None:
        if not family:
            return
        self.preview_name.setText(family)
        font = QtGui.QFont(family)
        font.setPixelSize(24)
        # The app stylesheet sets every label's font, so the preview's face and
        # size go in its own stylesheet; setFont alone would be overridden.
        escaped = family.replace("\\", "\\\\").replace('"', '\\"')
        self.preview.setStyleSheet(f'font-family: "{escaped}"; font-size: 24px;')
        metrics = QtGui.QFontMetrics(font)
        self.preview.setText(metrics.elidedText(self._sample, QtCore.Qt.TextElideMode.ElideRight,
                                                max(80, self.preview.width() - 4)))

    def _on_item_clicked(self, item, column: int) -> None:
        family = item.data(1, ROLE_FAMILY)
        if column == 0:
            self._favourites().toggle(family)
            self._paint_star(item, self._favourites().is_favourite(family))
            return
        self._choose(family)

    def _choose(self, family: str) -> None:
        if family:
            self.chosen.emit(family)
            self.close()

    def open_for(self, anchor: QtWidgets.QWidget, current: str, sample: str = "") -> None:
        """Show under `anchor` with `current` picked and `sample` (the selected text) as the preview."""
        self._current = current or ""
        sample = " ".join((sample or "").split())
        self._sample = sample[:60] or self.SAMPLE
        self.refill()
        self._show_preview(self._current or (self.font_list.topLevelItem(0).data(1, ROLE_FAMILY)
                                             if self.font_list.topLevelItemCount() else ""))
        below = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height()))
        screen = QtGui.QGuiApplication.screenAt(below) or QtGui.QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1920, 1080)
        x = min(below.x(), area.right() - self.width())
        y = below.y() if below.y() + self.height() <= area.bottom() else anchor.mapToGlobal(QtCore.QPoint(0, 0)).y() - self.height()
        self.move(max(area.left(), x), max(area.top(), y))
        self.show()
        self.search.setFocus()


class PickerFontComboBox(MFontComboBox):
    """The Character panel's font box: its drop-down is the font menu above.

    Typing a name into the box still works as before; the arrow opens the menu.
    `sample_text` (a callable) gives the selected text for the preview.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sample_text = lambda: ""
        self.picker: FontPickerPopup | None = None

    def showPopup(self):  # noqa: N802 — Qt's name
        if self.picker is None:
            self.picker = FontPickerPopup(self)
            self.picker.chosen.connect(self._apply_family)
        self.picker.open_for(self, self.currentText(), self.sample_text())

    def _apply_family(self, family: str) -> None:
        if family and family != self.currentText():
            self.setCurrentFont(QtGui.QFont(family))
            if self.currentText() != family:
                self.setCurrentText(family)
