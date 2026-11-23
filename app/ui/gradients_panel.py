"""The Gradients panel, as in Photoshop: folders of gradient tiles.

Each folder (Basics, Blues, Purples…, `core/gradient_presets.BUILTIN`) opens
and closes like Photoshop's; clicking a tile emits `chosen(start, end)`, and
the text controller gives the selected text layers that gradient
(`TextController.apply_gradient_preset`). **Reverse** swaps the two stops
before they are sent. "+" asks to save the selected text's own gradient
(`save_requested`), which goes into "My Gradients", kept in
`<user data>/gradients.json`; a saved one is removed from its tile's menu.
Which folders are open is remembered (`OPEN_KEY`).
"""

from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from core import gradient_presets as gp

OPEN_KEY = "gradients_panel/open"


def custom_path() -> str:
    from modules.utils.paths import get_user_data_dir

    return os.path.join(get_user_data_dir(), "gradients.json")


class FlowLayout(QtWidgets.QLayout):
    """Lays its items out left to right, wrapping to the width (Qt's example)."""

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items: list[QtWidgets.QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 — Qt's name
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._arrange(QtCore.QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QtCore.QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        gap = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + gap, 0
            if move:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x += hint.width() + gap
            line = max(line, hint.height())
        return y + line - rect.y()


class GradientTile(QtWidgets.QAbstractButton):
    def __init__(self, gradient: gp.Gradient, parent=None):
        super().__init__(parent)
        self.gradient = gradient
        self.setFixedSize(34, 34)
        self.setToolTip(gradient.name)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event):
        from app.ui.color_panel import _tokens

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -2)
        fill = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
        fill.setColorAt(0.0, QtGui.QColor(self.gradient.start))
        fill.setColorAt(1.0, QtGui.QColor(self.gradient.end))
        tokens = _tokens()
        hover = self.underMouse()
        painter.setPen(QtGui.QPen(QtGui.QColor(tokens["accent"] if hover else tokens["line_strong"]), 2 if hover else 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 4, 4)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class GradientFolder(QtWidgets.QWidget):
    """A folder row with an arrow; open, it shows its tiles."""

    toggled = QtCore.Signal(str, bool)

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.header = QtWidgets.QToolButton()
        self.header.setText(label)
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self.header.setAutoRaise(True)
        self.header.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.body = QtWidgets.QWidget()
        self.flow = FlowLayout(self.body)
        self.body.setVisible(False)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.header)
        layout.addWidget(self.body)
        self.header.toggled.connect(self._on_toggled)

    def set_open(self, open_: bool) -> None:
        self.header.setChecked(open_)

    def is_open(self) -> bool:
        return self.header.isChecked()

    def _on_toggled(self, open_: bool) -> None:
        self.header.setArrowType(QtCore.Qt.ArrowType.DownArrow if open_ else QtCore.Qt.ArrowType.RightArrow)
        self.body.setVisible(open_)
        self.toggled.emit(self.key, open_)

    def set_tiles(self, tiles: list[GradientTile]) -> None:
        while self.flow.count():
            widget = self.flow.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        for tile in tiles:
            self.flow.addWidget(tile)
        self.body.setMinimumHeight(0)
        self.body.updateGeometry()


class GradientsPanel(QtWidgets.QWidget):
    chosen = QtCore.Signal(str, str)  # start, end
    save_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toonGradientsPanel")
        self.folders: dict[str, GradientFolder] = {}
        self._custom: list[gp.Gradient] = gp.load_custom(custom_path())

        labels = {
            "Basics": self.tr("Basics"), "Blues": self.tr("Blues"), "Purples": self.tr("Purples"),
            "Pinks": self.tr("Pinks"), "Reds": self.tr("Reds"), "Oranges": self.tr("Oranges"),
            "Greens": self.tr("Greens"), "Yellows": self.tr("Yellows"),
            gp.CUSTOM_FOLDER: self.tr("My Gradients"),
        }
        opened = self._opened()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        keys = [gp.CUSTOM_FOLDER] + [name for name, _ in gp.BUILTIN]
        for key in keys:
            folder = GradientFolder(key, labels.get(key, key))
            self.folders[key] = folder
            layout.addWidget(folder)
        for name, gradients in gp.BUILTIN:
            self.folders[name].set_tiles([self._tile(g) for g in gradients])
        self._fill_custom()
        for key, folder in self.folders.items():
            folder.set_open(key in opened)
            folder.toggled.connect(self._remember_open)
        layout.addStretch(1)

        self.reverse_button = QtWidgets.QToolButton()
        self.reverse_button.setText("⇄ " + self.tr("Reverse"))
        self.reverse_button.setCheckable(True)
        self.reverse_button.setToolTip(self.tr("Apply gradients the other way round"))
        self.add_button = QtWidgets.QToolButton()
        self.add_button.setText("+")
        self.add_button.setToolTip(self.tr("Save the selected text's gradient to My Gradients"))
        self.add_button.clicked.connect(self.save_requested)
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(self.reverse_button)
        bar.addStretch(1)
        bar.addWidget(self.add_button)
        layout.addLayout(bar)

    # --- tiles ---------------------------------------------------------------

    def _tile(self, gradient: gp.Gradient, custom_index: int | None = None) -> GradientTile:
        tile = GradientTile(gradient)
        tile.clicked.connect(lambda _=False, g=gradient: self.choose(g))
        if custom_index is not None:
            tile.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(
                lambda pos, t=tile, i=custom_index: self._custom_menu(t, i).exec(t.mapToGlobal(pos))
            )
        return tile

    def tiles(self, key: str) -> list[GradientTile]:
        flow = self.folders[key].flow
        return [flow.itemAt(i).widget() for i in range(flow.count())]

    def choose(self, gradient: gp.Gradient) -> None:
        if self.reverse_button.isChecked():
            self.chosen.emit(gradient.end, gradient.start)
        else:
            self.chosen.emit(gradient.start, gradient.end)

    # --- the user's own -------------------------------------------------------

    def _fill_custom(self) -> None:
        folder = self.folders[gp.CUSTOM_FOLDER]
        folder.set_tiles([self._tile(g, i) for i, g in enumerate(self._custom)])
        folder.setVisible(bool(self._custom))

    def add_custom(self, start: str, end: str) -> None:
        self._custom = gp.add_custom(self._custom, start, end)
        gp.save_custom(custom_path(), self._custom)
        self._fill_custom()
        self.folders[gp.CUSTOM_FOLDER].set_open(True)

    def remove_custom(self, index: int) -> None:
        self._custom = gp.remove_custom(self._custom, index)
        gp.save_custom(custom_path(), self._custom)
        self._fill_custom()

    def _custom_menu(self, tile: GradientTile, index: int) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(tile)
        menu.addAction(self.tr("Delete Gradient"), lambda: self.remove_custom(index))
        return menu

    # --- open folders -----------------------------------------------------------

    def _opened(self) -> set[str]:
        value = QtCore.QSettings("ComicLabs", "ComicTranslate").value(OPEN_KEY)
        if value is None:
            return {"Basics", gp.CUSTOM_FOLDER}
        if isinstance(value, str):
            value = [value] if value else []
        return {v for v in value if isinstance(v, str)}

    def _remember_open(self, *_):
        opened = [key for key, folder in self.folders.items() if folder.is_open()]
        # An empty list reads back as nothing at all, which would mean "never set".
        QtCore.QSettings("ComicLabs", "ComicTranslate").setValue(OPEN_KEY, opened or "")
