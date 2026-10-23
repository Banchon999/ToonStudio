"""The frame drawn around the layer picked in the Layers panel.

Text and boxes are selected on the canvas when their row is picked; a patch or
a stroke cannot be, so without this nothing showed which "Patch 3" a row was —
the one over the face Clean wiped, or one over a bubble.

It is not part of the page. A plain QGraphicsItem, so `kind_of` gives None and
it is never listed as a layer, composited, saved or exported; its shape is
empty, so it is never hit by a click.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem


class LayerHighlight(QGraphicsItem):
    def __init__(self, rect: QRectF):
        super().__init__()
        self._rect = QRectF(rect)
        self.setZValue(1_000_000)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def set_rect(self, rect: QRectF) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(rect)

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def boundingRect(self) -> QRectF:
        # Room for the one-pixel pen at low zoom, where a screen pixel covers
        # several scene pixels; repaint only.
        return self._rect.adjusted(-16, -16, 16, 16)

    def shape(self) -> QPainterPath:
        return QPainterPath()

    def paint(self, painter, option, widget=None):
        # Light and dark dashes, one pixel on screen at any zoom, so the frame
        # shows over artwork of any colour.
        light = QPen(QColor(255, 255, 255), 0)
        light.setCosmetic(True)
        painter.setPen(light)
        painter.drawRect(self._rect)
        dark = QPen(QColor(0, 0, 0), 0, Qt.PenStyle.DashLine)
        dark.setCosmetic(True)
        painter.setPen(dark)
        painter.drawRect(self._rect)
