"""The Color panel, as in Photoshop and PhotoCraft.

Two swatches choose what the panel colours, the text's fill or its stroke
(outline); a saturation/brightness square and a hue strip pick the colour,
and hex and R/G/B fields type it. Dragging previews on the selected text
layers as it goes (`preview`) and settles as one undo step on release
(`committed`); a typed value commits at once. The last colours committed
are kept as a row of swatches (`RECENT_KEY`).

The panel holds no text state: `set_colors` shows the selected item's
colours, and the text controller decides what a colour does
(`TextController.preview_panel_color`/`commit_panel_color`).
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

FILL, STROKE = "fill", "stroke"
RECENT_KEY = "color_panel/recent"
RECENT_COUNT = 12


def _tokens():
    from core import theme_tokens
    from app.ui.dayu_widgets import dayu_theme

    return getattr(dayu_theme, "tokens", None) or theme_tokens.DARK


class SatValSquare(QtWidgets.QWidget):
    """Saturation left→right, brightness bottom→top, for the current hue."""

    moved = QtCore.Signal(float, float)  # saturation, value, 0..1
    released = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(140, 120)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.hue = 0.0
        self.sat = 0.0
        self.val = 0.0
        self._cache: QtGui.QImage | None = None
        self._cache_key = None

    def set_hsv(self, hue: float, sat: float, val: float) -> None:
        self.hue, self.sat, self.val = hue, sat, val
        self.update()

    def _image(self) -> QtGui.QImage:
        key = (round(self.hue, 4), self.width(), self.height())
        if self._cache is None or self._cache_key != key:
            image = QtGui.QImage(self.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            painter = QtGui.QPainter(image)
            rect = QtCore.QRectF(image.rect())
            across = QtGui.QLinearGradient(rect.topLeft(), rect.topRight())
            across.setColorAt(0.0, QtGui.QColor("white"))
            across.setColorAt(1.0, QtGui.QColor.fromHsvF(self.hue, 1.0, 1.0))
            painter.fillRect(rect, across)
            down = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
            down.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
            down.setColorAt(1.0, QtGui.QColor(0, 0, 0, 255))
            painter.fillRect(rect, down)
            painter.end()
            self._cache, self._cache_key = image, key
        return self._cache

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.drawImage(0, 0, self._image())
        x = self.sat * (self.width() - 1)
        y = (1.0 - self.val) * (self.height() - 1)
        ring = QtGui.QColor("black") if self.val > 0.6 and self.sat < 0.4 else QtGui.QColor("white")
        painter.setPen(QtGui.QPen(ring, 1.5))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QtCore.QPointF(x, y), 5, 5)

    def _pick(self, pos) -> None:
        w, h = max(1, self.width() - 1), max(1, self.height() - 1)
        self.sat = min(1.0, max(0.0, pos.x() / w))
        self.val = min(1.0, max(0.0, 1.0 - pos.y() / h))
        self.update()
        self.moved.emit(self.sat, self.val)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._pick(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.released.emit()


class HueStrip(QtWidgets.QWidget):
    """The hue, top (0°) to bottom (360°)."""

    moved = QtCore.Signal(float)
    released = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(18)
        self.setMinimumHeight(120)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.hue = 0.0

    def set_hue(self, hue: float) -> None:
        self.hue = hue
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        rect = QtCore.QRectF(self.rect()).adjusted(3, 0, -3, 0)
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        for i in range(7):
            gradient.setColorAt(i / 6, QtGui.QColor.fromHsvF((i / 6) % 1.0, 1.0, 1.0))
        painter.fillRect(rect, gradient)
        y = self.hue * (self.height() - 1)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor(_tokens()["text_1"]), 1.5))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QtCore.QRectF(0.75, y - 3, self.width() - 1.5, 6), 2, 2)

    def _pick(self, pos) -> None:
        self.hue = min(1.0, max(0.0, pos.y() / max(1, self.height() - 1)))
        self.update()
        self.moved.emit(self.hue)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._pick(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.released.emit()


class Swatch(QtWidgets.QAbstractButton):
    """A colour square; checked draws the accent ring (the panel's target)."""

    def __init__(self, color="#000000", size=22, parent=None):
        super().__init__(parent)
        self.color = QtGui.QColor(color)
        self.setFixedSize(size, size)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def set_color(self, color) -> None:
        self.color = QtGui.QColor(color)
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        tokens = _tokens()
        rect = QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -2)
        painter.setPen(QtGui.QPen(QtGui.QColor(tokens["line_strong"]), 1))
        painter.setBrush(self.color)
        painter.drawRoundedRect(rect, 3, 3)
        if self.isChecked():
            painter.setPen(QtGui.QPen(QtGui.QColor(tokens["accent"]), 2))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)


class ColorPanel(QtWidgets.QWidget):
    preview = QtCore.Signal(str, QtGui.QColor)  # target, colour — while dragging
    committed = QtCore.Signal(str, QtGui.QColor)  # target, colour — one undo step

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toonColorPanel")
        self._colors = {FILL: QtGui.QColor("#000000"), STROKE: QtGui.QColor("#ffffff")}
        self._target = FILL
        self._dragging = False

        self.fill_swatch = Swatch(self._colors[FILL], 30)
        self.fill_swatch.setToolTip(self.tr("Text colour: the panel sets the fill"))
        self.stroke_swatch = Swatch(self._colors[STROKE], 30)
        self.stroke_swatch.setToolTip(self.tr("Stroke colour: the panel sets the outline"))
        self.target_group = QtWidgets.QButtonGroup(self)
        for swatch in (self.fill_swatch, self.stroke_swatch):
            swatch.setCheckable(True)
            self.target_group.addButton(swatch)
        self.fill_swatch.setChecked(True)
        self.fill_swatch.clicked.connect(lambda: self.set_target(FILL))
        self.stroke_swatch.clicked.connect(lambda: self.set_target(STROKE))

        self.square = SatValSquare()
        self.hue_strip = HueStrip()
        self.square.moved.connect(self._on_square_moved)
        self.hue_strip.moved.connect(self._on_hue_moved)
        self.square.released.connect(self._on_released)
        self.hue_strip.released.connect(self._on_released)

        self.hex_edit = QtWidgets.QLineEdit()
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setFixedWidth(78)
        self.hex_edit.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(r"#?[0-9a-fA-F]{0,6}")))
        self.hex_edit.editingFinished.connect(self._on_hex_entered)
        # Plain fields: the app stylesheet leaves a button-less spin box no room for its number.
        self.rgb_fields = []
        for _ in range(3):
            field = QtWidgets.QLineEdit()
            field.setValidator(QtGui.QIntValidator(0, 255, field))
            field.setFixedWidth(44)
            field.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            field.editingFinished.connect(self._on_rgb_entered)
            self.rgb_fields.append(field)

        targets = QtWidgets.QHBoxLayout()
        targets.setSpacing(4)
        # Own source strings: "Fill" and "Stroke" are the bucket and the brush
        # stroke elsewhere, and the catalogue's fallback would answer with those.
        fill_label = QtWidgets.QLabel(self.tr("Text Fill"))
        stroke_label = QtWidgets.QLabel(self.tr("Text Stroke"))
        targets.addWidget(self.fill_swatch)
        targets.addWidget(fill_label)
        targets.addSpacing(10)
        targets.addWidget(self.stroke_swatch)
        targets.addWidget(stroke_label)
        targets.addStretch(1)

        picker = QtWidgets.QHBoxLayout()
        picker.setSpacing(6)
        picker.addWidget(self.square, 1)
        picker.addWidget(self.hue_strip)

        fields = QtWidgets.QHBoxLayout()
        fields.setSpacing(4)
        fields.addWidget(QtWidgets.QLabel("#"))
        fields.addWidget(self.hex_edit)
        fields.addSpacing(6)
        for name, field in zip(("R", "G", "B"), self.rgb_fields):
            fields.addWidget(QtWidgets.QLabel(name))
            fields.addWidget(field)
        fields.addStretch(1)

        self.recent_row = QtWidgets.QHBoxLayout()
        self.recent_row.setSpacing(2)
        recent_box = QtWidgets.QHBoxLayout()
        recent_label = QtWidgets.QLabel(self.tr("Recent"))
        recent_label.setToolTip(self.tr("Colours used last; click one to use it again"))
        recent_box.addWidget(recent_label)
        recent_box.addLayout(self.recent_row)
        recent_box.addStretch(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        layout.addLayout(targets)
        layout.addLayout(picker, 1)
        layout.addLayout(fields)
        layout.addLayout(recent_box)
        self._show(self._colors[FILL])
        self._fill_recent()

    # --- state ------------------------------------------------------------

    def target(self) -> str:
        return self._target

    def color(self, target: str | None = None) -> QtGui.QColor:
        return QtGui.QColor(self._colors[target or self._target])

    def set_target(self, target: str) -> None:
        self._target = target
        (self.fill_swatch if target == FILL else self.stroke_swatch).setChecked(True)
        self._show(self._colors[target])

    def set_colors(self, fill=None, stroke=None) -> None:
        """Show these colours (the selected item's) without changing anything."""
        if fill is not None and QtGui.QColor(fill).isValid():
            self._colors[FILL] = QtGui.QColor(fill)
            self.fill_swatch.set_color(fill)
        if stroke is not None and QtGui.QColor(stroke).isValid():
            self._colors[STROKE] = QtGui.QColor(stroke)
            self.stroke_swatch.set_color(stroke)
        if not self._dragging:
            self._show(self._colors[self._target])

    def _show(self, color: QtGui.QColor) -> None:
        hue, sat, val, _ = color.getHsvF()
        if hue < 0:  # grey: keep the hue the strip shows
            hue = self.hue_strip.hue
        self.square.set_hsv(hue, sat, val)
        self.hue_strip.set_hue(hue)
        self._show_fields(color)

    def _show_fields(self, color: QtGui.QColor) -> None:
        self.hex_edit.blockSignals(True)
        self.hex_edit.setText(color.name())
        self.hex_edit.blockSignals(False)
        for field, value in zip(self.rgb_fields, (color.red(), color.green(), color.blue())):
            field.blockSignals(True)
            field.setText(str(value))
            field.blockSignals(False)

    # --- picking ------------------------------------------------------------

    def _current_from_picker(self) -> QtGui.QColor:
        return QtGui.QColor.fromHsvF(self.hue_strip.hue % 1.0, self.square.sat, self.square.val)

    def _set_current(self, color: QtGui.QColor) -> None:
        self._colors[self._target] = QtGui.QColor(color)
        (self.fill_swatch if self._target == FILL else self.stroke_swatch).set_color(color)

    def _on_square_moved(self, *_):
        self._dragging = True
        color = self._current_from_picker()
        self._set_current(color)
        self._show_fields(color)
        self.preview.emit(self._target, color)

    def _on_hue_moved(self, hue: float):
        self.square.set_hsv(hue, self.square.sat, self.square.val)
        self._on_square_moved()

    def _on_released(self):
        self._dragging = False
        self._commit(self._colors[self._target])

    def _on_hex_entered(self):
        text = self.hex_edit.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        color = QtGui.QColor(text)
        if len(text) != 7 or not color.isValid():
            self._show_fields(self._colors[self._target])
            return
        if color != self._colors[self._target]:
            self.pick(color)

    def _on_rgb_entered(self, *_):
        try:
            values = [min(255, max(0, int(field.text() or 0))) for field in self.rgb_fields]
        except ValueError:
            self._show_fields(self._colors[self._target])
            return
        color = QtGui.QColor(*values)
        if color != self._colors[self._target]:
            self.pick(color)

    def pick(self, color) -> None:
        """Set the target's colour as if picked: shown, then committed."""
        color = QtGui.QColor(color)
        self._set_current(color)
        self._show(color)
        self._commit(color)

    def _commit(self, color: QtGui.QColor) -> None:
        self.committed.emit(self._target, QtGui.QColor(color))
        self._remember(color)

    # --- recent colours -------------------------------------------------------

    def recent(self) -> list[str]:
        value = QtCore.QSettings("ComicLabs", "ComicTranslate").value(RECENT_KEY) or []
        if isinstance(value, str):
            value = [value]
        return [v for v in value if isinstance(v, str) and QtGui.QColor(v).isValid()][:RECENT_COUNT]

    def _remember(self, color: QtGui.QColor) -> None:
        name = color.name()
        recent = [name] + [c for c in self.recent() if c != name]
        QtCore.QSettings("ComicLabs", "ComicTranslate").setValue(RECENT_KEY, recent[:RECENT_COUNT])
        self._fill_recent()

    def _fill_recent(self) -> None:
        while self.recent_row.count():
            widget = self.recent_row.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        for name in self.recent():
            swatch = Swatch(name, 18)
            swatch.setToolTip(name)
            swatch.clicked.connect(lambda _=False, name=name: self.pick(name))
            self.recent_row.addWidget(swatch)
