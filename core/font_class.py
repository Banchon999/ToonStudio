"""What a font menu filters by: a family's class (Serif, Sans Serif, Script…), Qt-free.

Ported from PhotoCraft's `crates/text/src/font_class.rs` (MIT/Apache-2.0),
itself following Photoshop's font menu: the class is read from the font's own
tables — OS/2 `sFamilyClass` (its high byte is the IBM class), the ten PANOSE
digits and `post.isFixedPitch` — and only where those say nothing, from the
family's name. A family no rule recognises has no class and shows under
"All Classes" only; that is most Thai fonts, which state neither.

`parse_tables` reads those fields from the raw table bytes, so the caller can
get the bytes any way it likes (`app/ui/font_picker.py` uses Qt's QRawFont).
"""

from __future__ import annotations

import re
import struct

SERIF, SLAB_SERIF, SANS_SERIF, SCRIPT = "serif", "slabSerif", "sansSerif", "script"
MONOSPACE, HANDWRITTEN, BLACKLETTER, DECORATIVE = "monospace", "handwritten", "blackletter", "decorative"

#: Every class, in menu order, with its English label.
CLASSES: tuple[tuple[str, str], ...] = (
    (SERIF, "Serif"),
    (SLAB_SERIF, "Slab Serif"),
    (SANS_SERIF, "Sans Serif"),
    (SCRIPT, "Script"),
    (MONOSPACE, "Monospace"),
    (HANDWRITTEN, "Handwritten"),
    (BLACKLETTER, "Blackletter"),
    (DECORATIVE, "Decorative"),
)

#: Name fragments (lowercase) that mark a blackletter face; the tables have no class for it.
_BLACKLETTER = ("fraktur", "blackletter", "black letter", "textura", "old english", "schwabacher", "rotunda")


def parse_tables(os2: bytes, post: bytes) -> tuple[int, tuple[int, ...], bool]:
    """(sFamilyClass, PANOSE digits, fixed pitch) from raw OS/2 and post tables.

    A missing or short table reads as "unknown" (0, all-zero PANOSE, False).
    """
    family_class, panose = 0, (0,) * 10
    if len(os2) >= 42:
        family_class = struct.unpack(">h", os2[30:32])[0]
        panose = tuple(os2[32:42])
    fixed = len(post) >= 16 and struct.unpack(">I", post[12:16])[0] != 0
    return family_class, panose, fixed


def classify(family: str, family_class: int, panose, fixed_pitch: bool) -> str | None:
    """The class key of a family, or None when neither its tables nor its name say."""
    name = family.lower()
    panose = tuple(panose) + (0,) * (10 - len(panose))

    def has(words) -> bool:
        return any(w in name for w in words)

    # Whole words of the name, so "Encode Sans" isn't read as a "code" font.
    words = [w for w in re.split(r"[^0-9a-z]+", name) if w]
    # PANOSE Latin Text proportion 9 is monospaced.
    if fixed_pitch or (panose[0] == 2 and panose[3] == 9):
        return MONOSPACE
    if has(_BLACKLETTER):
        return BLACKLETTER
    # PANOSE family kind: 3 Latin Hand Written, 4 Latin Decoratives, 5 Latin Symbol.
    if panose[0] == 3:
        return SCRIPT if (family_class >> 8) == 10 else HANDWRITTEN
    if panose[0] in (4, 5):
        return DECORATIVE
    ibm = family_class >> 8
    # 4 is Clarendon: bracketed serifs (Georgia), not slabs.
    if ibm in (1, 2, 3, 4, 7):
        return SERIF
    if ibm == 5:
        return SLAB_SERIF
    if ibm == 8:
        return SANS_SERIF
    if ibm in (9, 12):
        return DECORATIVE
    if ibm == 10:
        return HANDWRITTEN if has(("hand", "marker", "brush", "pen", "chalk")) else SCRIPT
    # PANOSE Latin Text serif style: 11-15 are sans; square (6) is a slab; the
    # rest, square coves (Georgia's bracketed serifs) included, are serifs.
    if panose[0] == 2:
        if 11 <= panose[1] <= 15:
            return SANS_SERIF
        if panose[1] == 6:
            return SLAB_SERIF
        if 2 <= panose[1] <= 10:
            return SERIF
    # Last, the name.
    if any(w in ("mono", "monospace", "monospaced", "code", "courier") or w.startswith("consol") for w in words):
        return MONOSPACE
    if has(("slab",)):
        return SLAB_SERIF
    if has(("sans", "grotesk", "grotesque", "gothic")):
        return SANS_SERIF
    if has(("serif", "roman", "garamond", "times", "bodoni", "baskerville", "caslon")):
        return SERIF
    if has(("hand", "marker", "brush", "chalk")):
        return HANDWRITTEN
    if has(("script",)):
        return SCRIPT
    return None


def matches(query: str, family: str) -> bool:
    """The font menu's search: every word of `query` somewhere in the name, any case."""
    name = family.casefold()
    return all(part in name for part in query.casefold().split())
