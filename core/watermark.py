"""A group's watermark, stamped on every exported page (Qt-free).

The owner's choices: text, a logo, or both; placed in one of nine positions
with a margin; on every page; only when exporting — the project is never
changed, and a PSD gets the watermark as a layer of its own, which can be
hidden.

Sizes are fractions of the page **width**, so the same settings suit a
1000×1500 manga page and an 800×5000 webtoon page alike (a height-based size
would be five times larger on the webtoon).

Drawing text needs Qt's font database, which export workers must never touch
(see `app/controllers/psd_exporter.warm_font_cache`). So the watermark is
drawn once, on the GUI thread, at `REFERENCE_WIDTH` (`app.ui.watermark`), and
a `WatermarkStamp` carries that raster to the workers, which only scale and
place it — numpy and PIL, no Qt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

import numpy as np

#: The page width the watermark is drawn for; every page scales it from here.
#: Large enough that typical pages (700–1600 px wide) only ever shrink it.
REFERENCE_WIDTH = 2000

TEXT = "text"
IMAGE = "image"
BOTH = "both"
KINDS = (TEXT, IMAGE, BOTH)

#: The nine positions, by row then column.
POSITIONS = (
    "top-left", "top-center", "top-right",
    "middle-left", "center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
)


@dataclass
class WatermarkSettings:
    enabled: bool = False
    kind: str = TEXT
    text: str = ""
    font_family: str = ""
    #: Height of the text, as a percentage of the page width.
    text_size: float = 3.0
    text_color: str = "#ffffff"
    #: An outline keeps the text readable on any artwork; 0 draws none.
    outline_width: float = 2.0
    outline_color: str = "#000000"
    #: The logo, copied into the user data folder when chosen.
    image_path: str = ""
    #: Width of the logo, as a percentage of the page width.
    image_size: float = 15.0
    #: 0–100.
    opacity: int = 60
    position: str = "bottom-right"
    #: Distance from the page's edges, as a percentage of the page width.
    margin: float = 2.0

    @classmethod
    def from_dict(cls, data: dict | None) -> "WatermarkSettings":
        data = dict(data or {})
        known = {f.name: f for f in fields(cls)}
        values = {}
        for name, spec in known.items():
            if name not in data or data[name] is None:
                continue
            raw = data[name]
            default = spec.default
            try:
                if isinstance(default, bool):
                    value = raw if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "yes", "on")
                elif isinstance(default, int):
                    value = int(float(raw))
                elif isinstance(default, float):
                    value = float(raw)
                else:
                    value = str(raw)
            except (TypeError, ValueError):
                continue
            values[name] = value
        settings = cls(**values)
        if settings.kind not in KINDS:
            settings.kind = TEXT
        if settings.position not in POSITIONS:
            settings.position = "bottom-right"
        settings.opacity = int(min(100, max(0, settings.opacity)))
        settings.text_size = float(min(30.0, max(0.5, settings.text_size)))
        settings.image_size = float(min(100.0, max(1.0, settings.image_size)))
        settings.margin = float(min(25.0, max(0.0, settings.margin)))
        settings.outline_width = float(min(20.0, max(0.0, settings.outline_width)))
        return settings

    def to_dict(self) -> dict:
        return asdict(self)

    def uses_text(self) -> bool:
        return self.kind in (TEXT, BOTH) and bool(self.text.strip())

    def uses_image(self) -> bool:
        return self.kind in (IMAGE, BOTH) and bool(self.image_path)

    def is_active(self) -> bool:
        """On, and with something to draw."""
        return self.enabled and (self.uses_text() or self.uses_image())


def place(page_w: int, page_h: int, mark_w: int, mark_h: int, position: str, margin: int) -> tuple[int, int]:
    """Top-left corner of a `mark_w`×`mark_h` watermark at `position`.

    A watermark larger than the page is placed from the page's corner rather
    than off it; `composite` clips whatever still overhangs.
    """
    row, col = divmod(POSITIONS.index(position) if position in POSITIONS else 8, 3)
    free_x, free_y = page_w - mark_w, page_h - mark_h
    x = (margin, free_x // 2, free_x - margin)[col]
    y = (margin, free_y // 2, free_y - margin)[row]
    return max(0, int(x)) if free_x >= 0 else 0, max(0, int(y)) if free_y >= 0 else 0


def composite(rgb: np.ndarray, rgba: np.ndarray, x: int, y: int) -> np.ndarray:
    """`rgb` with straight-alpha `rgba` laid over it at (`x`, `y`), clipped to the page."""
    out = np.array(rgb, copy=True)
    height, width = out.shape[:2]
    mh, mw = rgba.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + mw), min(height, y + mh)
    if x0 >= x1 or y0 >= y1:
        return out
    mark = rgba[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    alpha = mark[..., 3:4] / 255.0
    base = out[y0:y1, x0:x1, :3].astype(np.float32)
    out[y0:y1, x0:x1, :3] = np.clip(mark[..., :3] * alpha + base * (1.0 - alpha) + 0.5, 0, 255).astype(np.uint8)
    return out


@dataclass
class WatermarkStamp:
    """The watermark drawn for a `REFERENCE_WIDTH`-wide page, ready to place.

    Built on the GUI thread (`app.ui.watermark.build_stamp`); `for_page` and
    `apply` are pure numpy/PIL and safe on any thread.
    """

    rgba: np.ndarray
    position: str = "bottom-right"
    margin: float = 2.0
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    def for_page(self, page_w: int, page_h: int) -> tuple[int, int, np.ndarray] | None:
        """(x, y, rgba) of the watermark on a page of this size, or None when
        it would be under a pixel."""
        key = (int(page_w), int(page_h))
        if key in self._cache:
            return self._cache[key]
        scale = page_w / float(REFERENCE_WIDTH)
        h, w = self.rgba.shape[:2]
        mark_w, mark_h = max(0, round(w * scale)), max(0, round(h * scale))
        if mark_w < 1 or mark_h < 1:
            self._cache[key] = None
            return None
        if (mark_w, mark_h) == (w, h):
            mark = self.rgba
        else:
            from PIL import Image

            # Scaled with its colour premultiplied: straight alpha resampled as
            # is drags the colour of transparent pixels (often black) into the
            # edges of the text and the logo.
            premultiplied = self.rgba.astype(np.float32)
            premultiplied[..., :3] *= premultiplied[..., 3:4] / 255.0
            # Area averaging to shrink, bilinear to enlarge: neither overshoots.
            # Lanczos rings, which lifted a 70% watermark's alpha to 78%.
            resample = Image.BOX if mark_w < w else Image.BILINEAR
            channels = [
                np.asarray(Image.fromarray(premultiplied[..., c]).resize((mark_w, mark_h), resample))
                for c in range(4)
            ]
            scaled = np.stack(channels, axis=2)
            alpha = np.clip(scaled[..., 3:4], 0, 255)
            colour = np.where(alpha > 0, scaled[..., :3] * 255.0 / np.maximum(alpha, 1e-6), 0)
            mark = np.concatenate([np.clip(colour, 0, 255), alpha], axis=2).round().astype(np.uint8)
        x, y = place(page_w, page_h, mark_w, mark_h, self.position, round(page_w * self.margin / 100.0))
        result = (x, y, mark)
        self._cache[key] = result
        return result

    def apply(self, rgb: np.ndarray) -> np.ndarray:
        """`rgb` (H×W×3, or ×4) with the watermark on it."""
        page = np.asarray(rgb)
        if page.ndim != 3 or page.shape[2] < 3:
            return page
        placed = self.for_page(page.shape[1], page.shape[0])
        if placed is None:
            return page
        x, y, mark = placed
        out = composite(page[..., :3], mark, x, y)
        if page.shape[2] == 4:
            out = np.concatenate([out, page[..., 3:4]], axis=2)
        return out
