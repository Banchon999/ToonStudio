"""How a piece of lettering should be removed: paint, heal or inpaint (Qt-free).

Cleaning has three tools of very different cost and character, and each is
right for one kind of background:

* **colour** — a white, flat background (the usual speech bubble) is painted
  in its own colour. Exact, instant, and it leaves no trace of JPEG noise
  dragged in from the rim, which a fill grown from the surrounding pixels can.
* **heal** — a background that is smooth but not one white (a gradient, a
  tinted caption box, a soft glow) is filled from the pixels around the
  lettering, as the healing brush does with no source: the surroundings'
  tone carried through, no model.
* **model** — anything with texture (screentone, hatching, artwork) cannot
  be reproduced from its edge and goes to the inpainting model.

The decision is read from the *ring*: the few pixels right outside the region
to be filled, which are the pixels a fill would grow from.
"""

from __future__ import annotations

import numpy as np

from core.balloons import MIN_LIGHT
from core.paint import plane_residual

COLOUR = "colour"
HEAL = "heal"
MODEL = "model"

#: 95% of the ring must lie within this many levels of its median for the
#: background to count as one colour. JPEG noise on white is two or three;
#: a gradient across a line of text is five or more, and painted flat would
#: show as a patch.
FLAT_TOLERANCE = 4.0
#: The ring may stray this far from the best colour plane and still be smooth
#: enough to heal (flat 0.2–3, gradients 3–6, glow and see-through boxes 6–10,
#: artwork above — measured on real pages for the fast bubble fill).
MAX_HEAL_TEXTURE = 10.0
#: Ring pixels needed to judge at all.
MIN_RING = 20


def triage(image: np.ndarray, ring: np.ndarray,
           max_texture: float = MAX_HEAL_TEXTURE) -> tuple[str, tuple[int, int, int] | None, float]:
    """(method, colour, texture) for a region whose surroundings are `ring`.

    `colour` is set only for COLOUR. `texture` is the ring's `plane_residual`
    (infinity when the ring is too small to judge, which sends it to the model).
    """
    ring = np.asarray(ring, bool)
    if int(ring.sum()) < MIN_RING:
        return MODEL, None, float("inf")
    rgb = image[..., :3] if image.ndim == 3 else np.repeat(image[..., None], 3, axis=2)
    values = rgb[ring].astype(np.float32)
    median = np.median(values, axis=0)
    deviation = np.abs(values - median).max(axis=1)
    if float(median.min()) >= MIN_LIGHT and float(np.percentile(deviation, 95)) <= FLAT_TOLERANCE:
        return COLOUR, tuple(int(round(float(v))) for v in median), 0.0
    texture = plane_residual(image, ring)
    if texture <= max_texture:
        return HEAL, None, texture
    return MODEL, None, texture


def ring_of(region: np.ndarray, width: int = 3, within: np.ndarray | None = None) -> np.ndarray:
    """The `width`-pixel band just outside `region`, optionally kept `within`
    a mask (a bubble's inside, so its outline is never read as background)."""
    region = np.asarray(region, bool)
    grown = region.copy()
    for _ in range(int(width)):
        step = grown.copy()
        step[1:] |= grown[:-1]
        step[:-1] |= grown[1:]
        step[:, 1:] |= grown[:, :-1]
        step[:, :-1] |= grown[:, 1:]
        # Diagonals too, so the band is as wide at a corner as along an edge.
        step[1:, 1:] |= grown[:-1, :-1]
        step[1:, :-1] |= grown[:-1, 1:]
        step[:-1, 1:] |= grown[1:, :-1]
        step[:-1, :-1] |= grown[1:, 1:]
        grown = step
    ring = grown & ~region
    if within is not None:
        ring &= np.asarray(within, bool)
    return ring
