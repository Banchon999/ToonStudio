"""A round dial for picking a direction, as in Photoshop's layer styles.

Click or drag anywhere on the circle and the needle points there. The angle is
in screen degrees — 0 to the right, 90 straight down, clockwise — which is how
the gradient angle and the shadow offset are already measured, so the needle
points where the effect goes: toward the gradient's second colour, or where
the shadow falls. Shift snaps to 15°.

`angle_changed` follows the drag (for a number shown beside the dial);
`angle_committed` fires once, on release, so one drag is one undo step.
"""

from __future__ import annotations

import math

from PySide6 import QtCore, QtGui, QtWidgets

from core import theme_tokens

SNAP_DEGREES = 15.0


def angle_at(dx: float, dy: float) -> float:
    """Screen angle (0 right, 90 down) of the vector (dx, dy), in [0, 360)."""
    return math.degrees(math.atan2(dy, dx)) % 360.0


def snapped(angle: float, step: float = SNAP_DEGREES) -> float:
    return (round(angle / step) * step) % 360.0


def offset_for(angle: float, distance: float) -> tuple[float, float]:
    """The (dx, dy) a shadow `distance` px away in direction `angle` lands at."""
    rad = math.radians(angle)
    return (round(math.cos(rad) * distance, 2), round(math.sin(rad) * distance, 2))


def polar_of(dx: float, dy: float) -> tuple[float, float]:
    """(angle, distance) of an offset; a zero offset reads as 45° (down-right)."""
    distance = math.hypot(dx, dy)
    return (angle_at(dx, dy) if distance > 1e-9 else 45.0, distance)


class AngleDial(QtWidgets.QWidget):
    angle_changed = QtCore.Signal(float)
    angle_committed = QtCore.Signal(float)

    def __init__(self, angle: float = 0.0, parent=None):
        super().__init__(parent)
        self._angle = float(angle) % 360.0
        self._dragging = False
        self.setFixedSize(40, 40)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

    def angle(self) -> float:
        return self._angle

    def set_angle(self, angle: float) -> None:
        """Move the needle without emitting anything (for showing an item's value)."""
        self._angle = float(angle) % 360.0
        self.update()

    # --- input -------------------------------------------------------------

    def _angle_from(self, pos: QtCore.QPointF, modifiers) -> float:
        centre = QtCore.QPointF(self.width() / 2, self.height() / 2)
        angle = angle_at(pos.x() - centre.x(), pos.y() - centre.y())
        if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
            angle = snapped(angle)
        return angle

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.MouseButton.LeftButton or not self.isEnabled():
            return super().mousePressEvent(event)
        self._dragging = True
        self._set_from_mouse(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._set_from_mouse(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = False
            self._set_from_mouse(event)
            self.angle_committed.emit(self._angle)

    def _set_from_mouse(self, event):
        angle = self._angle_from(event.position(), event.modifiers())
        if abs(angle - self._angle) > 1e-6:
            self._angle = angle
            self.update()
            self.angle_changed.emit(angle)

    # --- drawing -----------------------------------------------------------

    def paintEvent(self, event):
        from app.ui.dayu_widgets import dayu_theme

        tokens = getattr(dayu_theme, "tokens", None) or theme_tokens.DARK
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -2)
        centre = rect.center()
        radius = rect.width() / 2
        painter.setPen(QtGui.QPen(QtGui.QColor(tokens["line_strong"]), 1.2))
        painter.setBrush(QtGui.QColor(tokens["raised"]))
        painter.drawEllipse(rect)
        # Ticks every 45°.
        painter.setPen(QtGui.QPen(QtGui.QColor(tokens["text_3"]), 1.0))
        for i in range(8):
            rad = math.radians(i * 45)
            outer = QtCore.QPointF(centre.x() + math.cos(rad) * radius, centre.y() + math.sin(rad) * radius)
            inner = QtCore.QPointF(centre.x() + math.cos(rad) * (radius - 3), centre.y() + math.sin(rad) * (radius - 3))
            painter.drawLine(inner, outer)
        accent = QtGui.QColor(tokens["accent"])
        if not self.isEnabled():
            accent = QtGui.QColor(tokens["text_3"])
        rad = math.radians(self._angle)
        tip = QtCore.QPointF(centre.x() + math.cos(rad) * (radius - 4), centre.y() + math.sin(rad) * (radius - 4))
        needle = QtGui.QPen(accent, 2.0)
        needle.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(needle)
        painter.drawLine(centre, tip)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(tip, 3.0, 3.0)
        painter.drawEllipse(centre, 2.0, 2.0)
        painter.end()
