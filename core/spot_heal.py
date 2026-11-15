"""Spot healing: find texture to heal from, without being told where (Qt-free).

The healing brush (`core.paint.heal`) needs a source: the user Alt+clicks a
patch of page whose texture should replace the mark, and the stroke's own
surroundings supply the tone. Spot healing chooses that source itself, as
Photoshop's spot healing brush does in its "proximity match" mode:

1. Around the region to fill, a *band* of known pixels is the template — what
   the texture must continue.
2. Every placement of that template nearby is scored by the squared difference
   over the band (computed for all placements at once by FFT correlation).
   Placements whose region would copy from another mark (`avoid`, e.g. the
   other letters of a caption) or from beyond the page are refused, and a
   placement farther away pays a little, so of two equal matches the nearer
   one — likelier to share the panel's lighting and content — wins.
3. The page shifted by the winning offset is the source, and `heal` takes its
   texture and the region's own surroundings' tone.

On screentone the best placement is one whole dot period away and the dots
carry straight through the region, which a smooth fill (`smooth_fill`) turns
into a flat grey patch. Each connected region gets its own source; when no
placement is allowed the region is smooth-filled instead.
"""

from __future__ import annotations

import numpy as np

from core.paint import heal, shifted

#: The template band around a region: this share of its larger side, clamped.
#: It must be at least one screentone period wide to tell dot phases apart.
BAND_SHARE = 0.35
MIN_BAND = 4
MAX_BAND = 14
#: How far to look for a source: this multiple of the region's larger side,
#: clamped. Farther means more choice and more FFT work.
SEARCH_SHARE = 1.5
MIN_SEARCH = 24
MAX_SEARCH = 160
#: A part larger than this is healed in tiles of this size (see `_pieces`).
TILE = 12
#: A placement this far away (the search radius) costs this much more.
DISTANCE_PENALTY = 0.15


def _dilate(mask: np.ndarray, steps: int) -> np.ndarray:
    grown = mask.copy()
    for _ in range(int(steps)):
        step = grown.copy()
        step[1:] |= grown[:-1]
        step[:-1] |= grown[1:]
        step[:, 1:] |= grown[:, :-1]
        step[:, :-1] |= grown[:, 1:]
        step[1:, 1:] |= grown[:-1, :-1]
        step[1:, :-1] |= grown[:-1, 1:]
        step[:-1, 1:] |= grown[1:, :-1]
        step[:-1, :-1] |= grown[1:, 1:]
        grown = step
    return grown


def _fast_length(n: int) -> int:
    """The smallest 2·3·5-smooth number ≥ n: FFT sizes pocketfft does quickly."""
    best = 1 << max(0, int(n - 1).bit_length())
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p235 = p35
            while p235 < n:
                p235 *= 2
            best = min(best, p235)
            p35 *= 3
        p5 *= 5
    return best


class _Correlator:
    """Valid-mode cross-correlations against kernels of one shape, by FFT.

    ``valid(spectrum)`` turns a product of `image(...)` and `kernel(...)`
    spectra back into ``out[y, x] = sum(kernel * image[y:y+kh, x:x+kw])``.
    Spectra are linear, so products can be summed before the one inverse.
    """

    def __init__(self, image_shape, kernel_shape):
        ih, iw = image_shape
        kh, kw = kernel_shape
        self.kh, self.kw, self.ih, self.iw = kh, kw, ih, iw
        self.shape = (_fast_length(ih + kh - 1), _fast_length(iw + kw - 1))

    def image(self, values: np.ndarray) -> np.ndarray:
        return np.fft.rfft2(values, self.shape)

    def kernel(self, values: np.ndarray) -> np.ndarray:
        return np.fft.rfft2(values[::-1, ::-1], self.shape)

    def valid(self, spectrum: np.ndarray) -> np.ndarray:
        full = np.fft.irfft2(spectrum, self.shape)
        return full[self.kh - 1:self.ih, self.kw - 1:self.iw]


def find_source_offset(image: np.ndarray, region: np.ndarray,
                       avoid: np.ndarray | None = None,
                       search: int | None = None) -> tuple[int, int] | None:
    """(dx, dy) such that the page `(dx, dy)` away is the best texture for `region`.

    `region` is one connected area to fill; `avoid` marks pixels that must not
    be copied (it always includes `region`). None when no placement is
    allowed — the region and its band would not fit anywhere clean nearby.
    `search` is how far to look (default: from the region's own size); a
    piece of a larger part must look past the whole part, since everything
    on it is still to be healed.
    """
    region = np.asarray(region, bool)
    ys, xs = np.nonzero(region)
    if ys.size == 0:
        return None
    height, width = region.shape
    avoid = region if avoid is None else (np.asarray(avoid, bool) | region)
    size = int(max(ys.max() - ys.min(), xs.max() - xs.min())) + 1
    band = int(np.clip(round(size * BAND_SHARE), MIN_BAND, MAX_BAND))
    if search is None:
        search = int(np.clip(round(size * SEARCH_SHARE), MIN_SEARCH, MAX_SEARCH))

    # The template: the region's box grown by the band, inside the page.
    ty0, ty1 = max(0, int(ys.min()) - band), min(height, int(ys.max()) + 1 + band)
    tx0, tx1 = max(0, int(xs.min()) - band), min(width, int(xs.max()) + 1 + band)
    hole = region[ty0:ty1, tx0:tx1]
    known = _dilate(hole, band) & ~avoid[ty0:ty1, tx0:tx1]
    if not known.any():
        return None
    # Where a placement may not land: anything it would copy into the hole, or
    # learn from in the band, must be clean page.
    footprint = (_dilate(hole, band) | hole).astype(np.float64)

    # The search area: the template's box grown by the search radius.
    sy0, sy1 = max(0, ty0 - search), min(height, ty1 + search)
    sx0, sx1 = max(0, tx0 - search), min(width, tx1 + search)
    area = image[sy0:sy1, sx0:sx1].astype(np.float64)
    if area.ndim == 2:
        area = area[..., None]
    template = image[ty0:ty1, tx0:tx1].astype(np.float64)
    if template.ndim == 2:
        template = template[..., None]
    weight = known.astype(np.float64)

    # Sum over the band of (area - template)^2, for every placement at once:
    # sum(w·a²) − 2·sum(w·t·a) + sum(w·t²), all channels in one inverse FFT.
    out_h, out_w = sy1 - sy0 - (ty1 - ty0) + 1, sx1 - sx0 - (tx1 - tx0) + 1
    if out_h <= 0 or out_w <= 0:
        return None
    corr = _Correlator(area.shape[:2], template.shape[:2])
    weight_spectrum = corr.kernel(weight)
    spectrum = 0
    constant = 0.0
    for channel in range(area.shape[2]):
        a = area[..., channel]
        t = template[..., channel]
        spectrum = spectrum + corr.image(a * a) * weight_spectrum - 2.0 * corr.image(a) * corr.kernel(weight * t)
        constant += float((weight * t * t).sum())
    cost = np.maximum(corr.valid(spectrum) + constant, 0.0) / float(weight.sum())

    overlap = corr.valid(corr.image(avoid[sy0:sy1, sx0:sx1].astype(np.float64)) * corr.kernel(footprint))
    blocked = overlap > 0.5
    cost[blocked] = np.inf

    # Placement index -> offset from where the template really is.
    oy = np.arange(cost.shape[0])[:, None] + sy0 - ty0
    ox = np.arange(cost.shape[1])[None, :] + sx0 - tx0
    distance = np.hypot(oy, ox) / float(search)
    cost = cost * (1.0 + DISTANCE_PENALTY * distance) + DISTANCE_PENALTY * distance
    best = np.unravel_index(int(np.argmin(cost)), cost.shape)
    if not np.isfinite(cost[best]):
        return None
    return int(ox[0, best[1]]), int(oy[best[0], 0])


def spot_heal(image: np.ndarray, region: np.ndarray, avoid: np.ndarray | None = None) -> np.ndarray:
    """`image` with `region` healed from texture found nearby, region by region.

    Each connected part of `region` (8-connected) gets its own source
    (`find_source_offset`) and is healed from it; a part with no allowed source
    is smooth-filled. Parts are done in turn, so a later one may copy from an
    earlier one's result but never from a part still to be healed. Every part
    is worked on inside a window just large enough for its search, never the
    whole page.
    """
    out = np.array(image, copy=True)
    region = np.asarray(region, bool)
    rows = np.flatnonzero(region.any(axis=1))
    if rows.size == 0:
        return out
    cols = np.flatnonzero(region.any(axis=0))
    # Only the region's surroundings take part: a brush stroke on an
    # 800×5000 webtoon slice must not label and grow the whole slice.
    reach = MAX_BAND + MAX_SEARCH + 4
    height, width = region.shape
    y0, y1 = max(0, int(rows[0]) - reach), min(height, int(rows[-1]) + 1 + reach)
    x0, x1 = max(0, int(cols[0]) - reach), min(width, int(cols[-1]) + 1 + reach)
    crop = np.s_[y0:y1, x0:x1]
    avoid_crop = None if avoid is None else np.asarray(avoid, bool)[crop]
    out[crop] = _spot_heal(out[crop], region[crop], avoid_crop)
    return out


def _pieces(part: np.ndarray, tile: int) -> list[np.ndarray]:
    """`part` cut into tiles of about `tile` pixels, outermost first.

    One source for a whole word cannot continue an edge that crosses it — a
    panel border, a speed line, the rim of a dark shape — and the tone
    correction smears grey where it fails. Small pieces each find their own,
    and filling from the outside in (onion order, by each piece's least
    distance to the part's edge) lets every piece match against pixels that
    are already page or already healed."""
    import mahotas

    ys, xs = np.nonzero(part)
    y0, x0 = int(ys.min()), int(xs.min())
    if max(int(ys.max()) - y0, int(xs.max()) - x0) + 1 <= tile:
        return [part]
    depth = mahotas.distance(part)
    pieces = []
    for ty in range(y0, int(ys.max()) + 1, tile):
        for tx in range(x0, int(xs.max()) + 1, tile):
            piece = np.zeros_like(part)
            piece[ty:ty + tile, tx:tx + tile] = part[ty:ty + tile, tx:tx + tile]
            if piece.any():
                pieces.append((float(depth[piece].min()), ty, tx, piece))
    pieces.sort(key=lambda item: item[:3])
    return [piece for *_key, piece in pieces]


def _spot_heal(out: np.ndarray, region: np.ndarray, avoid: np.ndarray | None) -> np.ndarray:
    import mahotas

    out = np.array(out, copy=True)
    pending = region.copy()
    if avoid is not None:
        pending |= avoid
    height, width = region.shape
    labels, count = mahotas.label(region, Bc=np.ones((3, 3), bool))
    boxes = mahotas.labeled.bbox(labels)
    for label in range(1, int(count) + 1):
        y0, y1, x0, x1 = (int(v) for v in boxes[label])
        box = np.s_[y0:y1, x0:x1]
        part_box = labels[box] == label
        # Every piece looks as far as the whole part needs: a piece of a long
        # stroke searching only around itself finds nothing but the stroke,
        # and falls back to a smooth fill (dark blobs along a panel border).
        part_size = max(y1 - y0, x1 - x0) + 2 * MAX_BAND
        search = int(np.clip(round(part_size * SEARCH_SHARE), MIN_SEARCH, MAX_SEARCH))
        for piece_box in _pieces(part_box, TILE):
            ys, xs = np.nonzero(piece_box)
            py0, py1 = y0 + int(ys.min()), y0 + int(ys.max()) + 1
            px0, px1 = x0 + int(xs.min()), x0 + int(xs.max()) + 1
            size = max(py1 - py0, px1 - px0)
            reach = int(np.clip(round(size * BAND_SHARE), MIN_BAND, MAX_BAND)) + search + 2
            wy0, wy1 = max(0, py0 - reach), min(height, py1 + reach)
            wx0, wx1 = max(0, px0 - reach), min(width, px1 + reach)
            window = np.s_[wy0:wy1, wx0:wx1]
            # The piece in window coordinates (the part's box may reach past
            # the window; the piece itself never does).
            piece = np.zeros((wy1 - wy0, wx1 - wx0), bool)
            oy0, oy1 = max(y0, wy0), min(y1, wy1)
            ox0, ox1 = max(x0, wx0), min(x1, wx1)
            piece[oy0 - wy0:oy1 - wy0, ox0 - wx0:ox1 - wx0] = piece_box[oy0 - y0:oy1 - y0, ox0 - x0:ox1 - x0]
            local = out[window]
            others = pending[window] & ~piece
            offset = find_source_offset(local, piece, pending[window], search)
            if offset is None:
                # Pixels still to be healed must not pin the fill's edge —
                # unless nothing else touches the piece.
                ring = _dilate(piece, 1) & ~piece
                pinned = ~others if (ring & ~others).any() else None
                out[window] = heal(local, np.zeros_like(local), piece, valid=pinned)
            else:
                source, valid = shifted(local, *offset)
                # Nor the tone correction's: only page and healed pixels do.
                out[window] = heal(local, source, piece, valid=valid & ~others)
            pending[window] &= ~piece
    return out
