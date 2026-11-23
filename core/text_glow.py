"""Outer glow around text (Qt-free): a soft halo of one colour, as Photoshop's
Outer Glow layer style.

The glow is made from the item's own drawn pixels — fill, outline and stroke
layers together — so it follows whatever the text looks like (warped, curved,
any font). Its alpha is that silhouette blurred three times with a box filter
(close to a gaussian, and cheap with cumulative sums), then lifted so the halo
is solid right against the letters and fades to nothing at `size` pixels.
"""

from __future__ import annotations

import numpy as np

#: How strongly the blurred silhouette is lifted. A plain blur is only half
#: opaque at the letters' edge, which reads as a faint grey haze rather than a
#: glow; 2.2 makes the first pixels out solid and keeps the fade.
LIFT = 2.2


def box_radius(size: float) -> int:
    """Radius of each of the three box passes for a glow reaching `size` px."""
    return max(1, int(round(float(size) / 3.0)))


def glow_reach(size: float) -> float:
    """How far past the drawn pixels the glow reaches, in item pixels."""
    if size <= 0:
        return 0.0
    return 3.0 * box_radius(size) + 2.0


def _box_blur_axis(values: np.ndarray, radius: int, axis: int) -> np.ndarray:
    pad = [(0, 0), (0, 0)]
    pad[axis] = (radius + 1, radius)
    padded = np.pad(values, pad)
    total = np.cumsum(padded, axis=axis, dtype=np.float64)
    width = 2 * radius + 1
    if axis == 0:
        out = total[width:] - total[:-width]
    else:
        out = total[:, width:] - total[:, :-width]
    return out / width


def glow_alpha(silhouette: np.ndarray, size: float) -> np.ndarray:
    """Glow alpha (0–1 float) from a silhouette alpha (uint8 or 0–1 float), same shape."""
    alpha = np.asarray(silhouette, dtype=np.float64)
    if alpha.max(initial=0.0) > 1.0:
        alpha = alpha / 255.0
    if size <= 0 or alpha.size == 0:
        return np.zeros_like(alpha)
    radius = box_radius(size)
    blurred = alpha
    for _ in range(3):
        blurred = _box_blur_axis(blurred, radius, axis=0)
        blurred = _box_blur_axis(blurred, radius, axis=1)
    return np.clip(blurred * LIFT, 0.0, 1.0)


def glow_rgba(silhouette: np.ndarray, size: float, rgba: tuple[int, int, int, int]) -> np.ndarray:
    """The glow as a premultiplied RGBA uint8 image (what Qt's ARGB32_Premultiplied holds as BGRA)."""
    alpha = glow_alpha(silhouette, size) * (rgba[3] / 255.0)
    out = np.empty(alpha.shape + (4,), np.uint8)
    for channel, value in enumerate(rgba[:3]):
        out[..., channel] = np.round(alpha * value).astype(np.uint8)
    out[..., 3] = np.round(alpha * 255.0).astype(np.uint8)
    return out
