"""Drawing the watermark (`core.watermark`) — on the GUI thread only.

`build_stamp` draws the text and/or logo once, for a page
`core.watermark.REFERENCE_WIDTH` wide, and returns a `WatermarkStamp` the
export workers scale and place without touching Qt. The logo sits above the
text, both centred on each other.
"""

from __future__ import annotations

import logging
import os
import shutil

import numpy as np
from PySide6 import QtCore, QtGui

from core.watermark import REFERENCE_WIDTH, WatermarkSettings, WatermarkStamp
from modules.utils.paths import get_user_data_dir

logger = logging.getLogger(__name__)

#: `WatermarkSettings.outline_width` is in pixels on a page this wide.
OUTLINE_PAGE_WIDTH = 1000


def logo_store_path(source: str) -> str:
    """Where a chosen logo is kept: a copy in the user data folder, so the
    watermark still works after the original is moved or deleted."""
    folder = os.path.join(get_user_data_dir("ComicTranslate"), "watermark")
    ext = os.path.splitext(source)[1].lower() or ".png"
    return os.path.join(folder, f"logo{ext}")


def keep_logo(source: str) -> str:
    """Copy `source` into the user data folder and return the copy's path."""
    target = logo_store_path(source)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.abspath(source) != os.path.abspath(target):
        # Any previous logo with another extension goes, so only one is kept.
        folder = os.path.dirname(target)
        for name in os.listdir(folder):
            if name.startswith("logo.") and os.path.join(folder, name) != target:
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass
        shutil.copyfile(source, target)
    return target


def _text_path(settings: WatermarkSettings) -> tuple[QtGui.QPainterPath, float]:
    font = QtGui.QFont(settings.font_family) if settings.font_family else QtGui.QFont()
    size = max(1.0, REFERENCE_WIDTH * settings.text_size / 100.0)
    font.setPixelSize(int(round(size)))
    path = QtGui.QPainterPath()
    lines = settings.text.strip().splitlines() or [""]
    metrics = QtGui.QFontMetricsF(font)
    widths = [metrics.horizontalAdvance(line) for line in lines]
    widest = max(widths) if widths else 0.0
    for index, (line, width) in enumerate(zip(lines, widths)):
        path.addText(QtCore.QPointF((widest - width) / 2.0, metrics.ascent() + index * metrics.lineSpacing()),
                     font, line)
    return path, size


def _qimage_to_rgba(image: QtGui.QImage) -> np.ndarray:
    image = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    rows = np.array(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    return rows[:, : image.width() * 4].reshape(image.height(), image.width(), 4).copy()


def render_rgba(settings: WatermarkSettings) -> np.ndarray | None:
    """The watermark for a `REFERENCE_WIDTH`-wide page, straight-alpha RGBA."""
    logo = None
    if settings.uses_image():
        if os.path.isfile(settings.image_path):
            loaded = QtGui.QImage(settings.image_path)
            if not loaded.isNull():
                logo_w = max(1, round(REFERENCE_WIDTH * settings.image_size / 100.0))
                logo = loaded.scaledToWidth(logo_w, QtCore.Qt.TransformationMode.SmoothTransformation)
        else:
            logger.warning("Watermark logo is missing: %s", settings.image_path)

    path = None
    outline = 0.0
    if settings.uses_text():
        path, size = _text_path(settings)
        outline = settings.outline_width * REFERENCE_WIDTH / OUTLINE_PAGE_WIDTH
        if path.isEmpty():
            path = None

    if logo is None and path is None:
        return None

    text_rect = QtCore.QRectF()
    if path is not None:
        text_rect = path.boundingRect().adjusted(-outline, -outline, outline, outline)
    gap = round(text_rect.height() * 0.25) if (logo is not None and path is not None) else 0
    width = max(logo.width() if logo is not None else 0, int(np.ceil(text_rect.width())))
    height = (logo.height() if logo is not None else 0) + gap + int(np.ceil(text_rect.height()))
    if width < 1 or height < 1:
        return None

    canvas = QtGui.QImage(width, height, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(canvas)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
    top = 0
    if logo is not None:
        painter.drawImage(QtCore.QPointF((width - logo.width()) / 2.0, 0), logo)
        top = logo.height() + gap
    if path is not None:
        painter.translate((width - text_rect.width()) / 2.0 - text_rect.left(), top - text_rect.top())
        if outline > 0:
            pen = QtGui.QPen(QtGui.QColor(settings.outline_color), outline * 2.0)
            pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.strokePath(path, pen)
        painter.fillPath(path, QtGui.QColor(settings.text_color))
    painter.end()

    rgba = _qimage_to_rgba(canvas)
    rgba[..., 3] = (rgba[..., 3].astype(np.float32) * (settings.opacity / 100.0)).round().astype(np.uint8)
    return rgba


def build_stamp(settings: WatermarkSettings | None) -> WatermarkStamp | None:
    """The stamp for export, or None when the watermark is off or empty.

    Call on the GUI thread, before handing work to an export worker."""
    if settings is None or not settings.is_active():
        return None
    try:
        rgba = render_rgba(settings)
    except Exception:
        logger.exception("Could not draw the watermark; exporting without it")
        return None
    if rgba is None or not rgba[..., 3].any():
        return None
    return WatermarkStamp(rgba=rgba, position=settings.position, margin=settings.margin)
