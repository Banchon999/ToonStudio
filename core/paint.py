"""Brush maths for the pixel tools: dabs, strokes, sampling (Qt-free).

A stroke is a run of round dabs stamped into a float *coverage* map, 0..1,
the size of the image being painted. Each dab adds ``flow`` of what is still
uncovered (``c += (1 - c) * dab * flow``), so going over the same place builds
up towards full coverage and never past it — which is what makes a low-flow
brush feel like airbrushing rather than like stacking opaque stamps. The
stroke's *opacity* is applied once, at the end, as a ceiling on the whole
coverage map: a 50% stroke stays 50% however many times it crosses itself.

Kept free of Qt so the maths is tested as arrays; the canvas session feeds it
points and turns the coverage into a patch.
"""

from __future__ import annotations

import math

import numpy as np


def dab(radius: float, hardness: float = 1.0) -> np.ndarray:
    """A round brush tip as float alpha, (2r+1) square, 1 at the centre.

    Hardness 1 is a solid disc with a one-pixel anti-aliased rim; hardness 0
    falls off smoothly from the centre to the edge; in between, the solid core
    covers `hardness` of the radius and the rest ramps down. A radius below
    half a pixel is still a one-pixel dab, so a tiny brush always paints.
    """
    radius = max(0.5, float(radius))
    hardness = min(1.0, max(0.0, float(hardness)))
    size = int(math.ceil(radius))
    yy, xx = np.mgrid[-size:size + 1, -size:size + 1].astype(np.float32)
    distance = np.sqrt(xx * xx + yy * yy)
    if hardness >= 1.0:
        # One-pixel ramp across the edge: anti-aliased, but otherwise solid.
        alpha = np.clip(radius + 0.5 - distance, 0.0, 1.0)
    else:
        core = radius * hardness
        span = max(radius - core, 1e-6)
        t = np.clip((distance - core) / span, 0.0, 1.0)
        # Smoothstep down from the core to the rim, then the same one-pixel
        # anti-aliasing at the rim so a soft brush has no hard outer ring.
        alpha = 1.0 - t * t * (3.0 - 2.0 * t)
        alpha *= np.clip(radius + 0.5 - distance, 0.0, 1.0)
    alpha[size, size] = max(alpha[size, size], 1.0)
    return alpha.astype(np.float32)


def stamp(coverage: np.ndarray, x: float, y: float, radius: float,
          hardness: float = 1.0, flow: float = 1.0):
    """Add one dab centred at (x, y) into `coverage` in place.

    Returns the touched rect as (x0, y0, x1, y1), exclusive ends, clipped to
    the map, or None when the dab lies entirely outside it.
    """
    flow = min(1.0, max(0.0, float(flow)))
    if flow <= 0.0:
        return None
    tip = dab(radius, hardness) * flow
    half = tip.shape[0] // 2
    cx, cy = int(round(x)), int(round(y))
    height, width = coverage.shape[:2]
    x0, y0 = cx - half, cy - half
    x1, y1 = x0 + tip.shape[1], y0 + tip.shape[0]
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(width, x1), min(height, y1)
    if cx0 >= cx1 or cy0 >= cy1:
        return None
    region = coverage[cy0:cy1, cx0:cx1]
    piece = tip[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
    region += (1.0 - region) * piece
    np.clip(region, 0.0, 1.0, out=region)
    return cx0, cy0, cx1, cy1


def spacing_for(radius: float) -> float:
    """Distance between dabs: 15% of the diameter, at least a pixel. Closer
    wastes time for no visible gain; further shows the dabs as beads."""
    return max(1.0, 0.3 * float(radius))


def dab_positions(start, end, spacing: float, carry: float = 0.0):
    """Dab centres from `start` to `end`, every `spacing` pixels.

    `carry` is how far along the previous segment's last gap the brush already
    was, so dabs stay evenly spaced across the many short segments a mouse
    drag arrives as. Returns (positions, new_carry).
    """
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])
    length = math.hypot(ex - sx, ey - sy)
    spacing = max(1e-3, float(spacing))
    positions = []
    travelled = spacing - carry if carry > 0 else spacing
    while travelled <= length + 1e-9:
        t = travelled / length if length else 0.0
        positions.append((sx + (ex - sx) * t, sy + (ey - sy) * t))
        travelled += spacing
    new_carry = (length - (travelled - spacing)) if positions else carry + length
    return positions, new_carry


def sample(image: np.ndarray, x: float, y: float, size: int = 3):
    """The mean colour of a size×size window centred on (x, y), clipped to
    the image, as an (r, g, b) tuple of ints — or None outside the image."""
    height, width = image.shape[:2]
    cx, cy = int(round(x)), int(round(y))
    if not (0 <= cx < width and 0 <= cy < height):
        return None
    half = max(0, int(size) // 2)
    window = image[max(0, cy - half):cy + half + 1, max(0, cx - half):cx + half + 1]
    if window.ndim == 2:
        value = int(round(float(window.mean())))
        return value, value, value
    mean = window[..., :3].reshape(-1, 3).astype(np.float64).mean(axis=0)
    return tuple(int(round(v)) for v in mean)


def pressure_scale(pressure, enabled: bool) -> float:
    """How much a tablet pressure reading scales size or flow. A mouse (no
    reading) or the option off is full; a reading is clamped so a feather-light
    touch still leaves a mark."""
    if not enabled or pressure is None:
        return 1.0
    return min(1.0, max(0.05, float(pressure)))


def shifted(image: np.ndarray, dx: int, dy: int):
    """`image` sampled `(dx, dy)` pixels away: ``out[y, x] = image[y + dy, x + dx]``.

    This is what a clone stamp paints from. Returns ``(out, valid)``, where
    `valid` marks the pixels whose source lies inside the image; the rest of
    `out` is zero and must not be painted, since there is nothing to clone.
    """
    dx, dy = int(round(dx)), int(round(dy))
    height, width = image.shape[:2]
    out = np.zeros_like(image)
    valid = np.zeros((height, width), bool)
    # Destination rows/cols whose source row/col is inside the image.
    y0, y1 = max(0, -dy), min(height, height - dy)
    x0, x1 = max(0, -dx), min(width, width - dx)
    if y0 < y1 and x0 < x1:
        out[y0:y1, x0:x1] = image[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
        valid[y0:y1, x0:x1] = True
    return out, valid


#: Kept for callers that pass a sweep count; the solver no longer needs one.
HEAL_ITERATIONS = 400
SMOOTH_FILL_ITERATIONS = 80

#: Sweeps and over-relaxation on every grid above the coarsest. The start is
#: the coarser grid's answer, so only the fine detail is left to settle.
MEMBRANE_FINE_SWEEPS = 30
MEMBRANE_FINE_OMEGA = 1.7
MEMBRANE_COARSE_SWEEPS = 400
MEMBRANE_COARSE_OMEGA = 1.85
#: Stop sweeping once no pixel moves by more than this (grey levels).
MEMBRANE_TOLERANCE = 0.01


def solve_membrane(values: np.ndarray, known: np.ndarray, unknown: np.ndarray) -> np.ndarray:
    """`values` with the `unknown` pixels replaced by the smoothest surface
    through the `known` ones (Laplace's equation, per channel).

    Pixels in neither mask take no part: they are not read and do not act as
    a boundary, so a hole at the image edge is free there rather than pulled
    towards zero. `values` is (H, W, C) float.

    Solved coarse to fine. The problem is halved until it is tiny, solved
    there, and each finer grid starts from the coarser answer enlarged, so a
    few red-black over-relaxed sweeps per grid are enough. Plain relaxation
    from one grid moves information one pixel per sweep and never settles a
    wide hole; this does, in a fraction of the time.

    The scheme (cascadic multigrid with SOR) follows PhotoCraft's
    `crates/algo/src/poisson.rs` (MIT OR Apache-2.0, (c) ArtCraft Team and the
    PhotoCraft contributors), rewritten for numpy with red-black ordering.
    """
    values = np.array(values, dtype=np.float32)
    known = np.asarray(known, bool) & ~np.asarray(unknown, bool)
    unknown = np.asarray(unknown, bool)
    if not unknown.any() or not known.any():
        return values
    _membrane(values, known, unknown, 0)
    return values


def _membrane(v: np.ndarray, known: np.ndarray, unknown: np.ndarray, depth: int) -> None:
    height, width = unknown.shape
    mean = v[known].mean(axis=0)
    if height >= 8 and width >= 8 and int(unknown.sum()) > 64 and depth < 16:
        ch, cw = (height + 1) // 2, (width + 1) // 2
        pad = ((0, ch * 2 - height), (0, cw * 2 - width))
        k = np.pad(known, pad).reshape(ch, 2, cw, 2)
        u = np.pad(unknown, pad).reshape(ch, 2, cw, 2)
        vv = np.pad(np.where(known[..., None], v, 0.0), pad + ((0, 0),)).reshape(ch, 2, cw, 2, -1)
        count = k.sum(axis=(1, 3))
        # A coarse pixel is known when any of its four is, at their mean.
        coarse_known = count > 0
        coarse = vv.sum(axis=(1, 3)) / np.maximum(count, 1)[..., None]
        coarse_unknown = u.any(axis=(1, 3)) & ~coarse_known
        if coarse_known.any() and coarse_unknown.any():
            _membrane(coarse, coarse_known, coarse_unknown, depth + 1)
        # Coarse pixels outside both masks hold nothing; give the enlargement
        # something neutral to blend with.
        coarse[~(coarse_known | coarse_unknown)] = mean
        fy = np.clip((np.arange(height) + 0.5) / 2.0 - 0.5, 0, ch - 1)
        fx = np.clip((np.arange(width) + 0.5) / 2.0 - 0.5, 0, cw - 1)
        y0 = np.floor(fy).astype(int); y1 = np.minimum(y0 + 1, ch - 1); ty = (fy - y0)[:, None, None]
        x0 = np.floor(fx).astype(int); x1 = np.minimum(x0 + 1, cw - 1); tx = (fx - x0)[None, :, None]
        top = coarse[y0][:, x0] * (1 - tx) + coarse[y0][:, x1] * tx
        bottom = coarse[y1][:, x0] * (1 - tx) + coarse[y1][:, x1] * tx
        guess = top * (1 - ty) + bottom * ty
        v[unknown] = guess[unknown]
        _relax(v, known, unknown, MEMBRANE_FINE_SWEEPS, MEMBRANE_FINE_OMEGA)
    else:
        v[unknown] = mean
        _relax(v, known, unknown, MEMBRANE_COARSE_SWEEPS, MEMBRANE_COARSE_OMEGA)


def _relax(v: np.ndarray, known: np.ndarray, unknown: np.ndarray, sweeps: int, omega: float) -> None:
    """Red-black successive over-relaxation of the unknown pixels, in place,
    on the bounding box of the unknown pixels only."""
    ys, xs = np.nonzero(unknown)
    height, width = unknown.shape
    y0, y1 = max(0, int(ys.min()) - 1), min(height, int(ys.max()) + 2)
    x0, x1 = max(0, int(xs.min()) - 1), min(width, int(xs.max()) + 2)
    block = v[y0:y1, x0:x1]
    free = unknown[y0:y1, x0:x1]
    part = np.pad((known | unknown)[y0:y1, x0:x1].astype(np.float32), 1)
    count = part[:-2, 1:-1] + part[2:, 1:-1] + part[1:-1, :-2] + part[1:-1, 2:]
    inner = part[1:-1, 1:-1][..., None]
    yy, xx = np.indices(free.shape)
    passes = []
    for parity in (0, 1):
        colour = free & (((yy + xx) & 1) == parity) & (count > 0)
        if colour.any():
            # Dense weights, zero off this colour: whole-array arithmetic is
            # several times faster than indexing the pixels out and back.
            gain = np.where(colour, omega, 0.0).astype(np.float32)[..., None]
            share = np.where(colour, 1.0 / np.maximum(count, 1.0), 0.0).astype(np.float32)[..., None]
            passes.append((gain, share))
    buffer = np.zeros((block.shape[0] + 2, block.shape[1] + 2, block.shape[2]), np.float32)
    total = np.empty_like(block)
    for sweep in range(int(sweeps)):
        for gain, share in passes:
            # Pixels taking no part count as absent, whatever they hold.
            np.multiply(block, inner, out=buffer[1:-1, 1:-1])
            np.add(buffer[:-2, 1:-1], buffer[2:, 1:-1], out=total)
            total += buffer[1:-1, :-2]
            total += buffer[1:-1, 2:]
            total *= share
            total -= block
            total *= gain            # zero off this colour, so nothing else moves
            block += total
        # Checking costs a pass over the array; every fourth sweep is enough.
        moved = float(np.abs(total).max()) if sweep % 4 == 3 else np.inf
        if moved < MEMBRANE_TOLERANCE:
            break


def heal(dest: np.ndarray, source: np.ndarray, region: np.ndarray,
         valid: np.ndarray | None = None, iterations: int = HEAL_ITERATIONS) -> np.ndarray:
    """The healing brush: `source`'s detail in `dest`'s tone.

    Inside `region` the result is ``source + correction``, where the
    correction equals ``dest − source`` on the ring of pixels just outside
    the region and is as smooth as possible inside it (Laplace's equation,
    relaxed from a blurred estimate). So the texture comes from where the
    user cloned from while the brightness and colour flow in from the
    stroke's own surroundings — and nothing *inside* the region (the mark
    being healed away) takes part, which a plain blur of the destination
    would let bleed into the result. Outside `region` the result is `dest`.
    `valid` (optional) marks where `source` exists at all — a clone sampled
    from beyond the page edge has none; such ring pixels are left free
    rather than pinned to a meaningless difference. Works on the region's
    bounding box only.
    """
    region = np.asarray(region, bool)
    out = dest.copy()
    ys, xs = np.nonzero(region)
    if ys.size == 0:
        return out
    height, width = region.shape
    y0, y1 = max(0, int(ys.min()) - 1), min(height, int(ys.max()) + 2)
    x0, x1 = max(0, int(xs.min()) - 1), min(width, int(xs.max()) + 2)
    inside = region[y0:y1, x0:x1]
    d = dest[y0:y1, x0:x1].astype(np.float32)
    s = source[y0:y1, x0:x1].astype(np.float32)
    if d.ndim == 2:
        d, s = d[..., None], s[..., None]
    diff = d - s
    # The fixed boundary: pixels outside the region that touch it.
    grown = inside.copy()
    grown[1:] |= inside[:-1]
    grown[:-1] |= inside[1:]
    grown[:, 1:] |= inside[:, :-1]
    grown[:, :-1] |= inside[:, 1:]
    ring = grown & ~inside
    free = inside
    if valid is not None:
        has_source = np.asarray(valid, bool)[y0:y1, x0:x1]
        free = inside | (ring & ~has_source)
        ring = ring & has_source
    if not ring.any():
        # No surroundings to take a tone from (the region is the whole image,
        # or nothing around it has a source): plain clone.
        corr = np.zeros_like(diff)
    else:
        # Pixels outside both the ring and the region — past the crop, or a
        # corner the ring skips — take no part, so they are no zero boundary.
        corr = solve_membrane(diff, ring, free)
    healed = np.clip(s + corr, 0, 255)
    if dest.ndim == 2:
        healed = healed[..., 0]
    block = out[y0:y1, x0:x1]
    block[inside] = np.round(healed[inside]).astype(dest.dtype)
    return out


def smooth_fill(image: np.ndarray, region: np.ndarray,
                iterations: int = SMOOTH_FILL_ITERATIONS) -> np.ndarray:
    """`image` with `region` filled smoothly from the pixels just outside it.

    The fill matches the surroundings at the region's edge and is as smooth
    as possible inside (Laplace's equation — `heal` with no source). On a flat
    background that is the background's colour; on a gradient it is the
    gradient, where any single colour leaves a visible patch.
    """
    image = np.asarray(image)
    return heal(image, np.zeros_like(image), region, iterations=iterations)


def plane_residual(image: np.ndarray, ring: np.ndarray, percentile: float = 90.0) -> float:
    """How far `ring`'s pixels stray from the best flat-or-sloped colour plane.

    Fits ``colour = a·x + b·y + c`` per channel to the ring's pixels and returns
    the given percentile of the largest per-channel deviation. A flat fill or
    a smooth gradient scores near zero; dots, screentone and artwork score
    high — which is what tells a background a smooth fill can reproduce from
    one it cannot. Infinity when the ring is too small to judge.
    """
    ys, xs = np.nonzero(ring)
    if ys.size < 20:
        return float("inf")
    values = np.asarray(image)[ring].astype(np.float64)
    if values.ndim == 1:
        values = values[:, None]
    design = np.column_stack([xs, ys, np.ones_like(xs)]).astype(np.float64)
    coef, *_ = np.linalg.lstsq(design, values, rcond=None)
    residual = np.abs(values - design @ coef).max(axis=1)
    return float(np.percentile(residual, percentile))
