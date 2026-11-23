"""The Gradients panel's presets, in folders as Photoshop shows them, Qt-free.

A text item's gradient has two stops: its own text colour and
`gradient_color` (`TextBlockItem.set_gradient`), so a preset is a pair of
colours. Built-in folders are fixed; the user's own gradients ("My
Gradients") are kept in `<user data>/gradients.json` as a list of
{"name", "start", "end"}.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

CUSTOM_FOLDER = "My Gradients"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Gradient:
    name: str
    start: str  # "#rrggbb"
    end: str


def _g(name, start, end) -> Gradient:
    return Gradient(name, start, end)


# Folder name → gradients, in menu order. English names; the panel shows
# the folder names translated.
BUILTIN: tuple[tuple[str, tuple[Gradient, ...]], ...] = (
    ("Basics", (
        _g("Black to White", "#000000", "#ffffff"),
        _g("White to Black", "#ffffff", "#000000"),
        _g("Grey Fade", "#3a3a3a", "#bdbdbd"),
        _g("Silver", "#f2f2f2", "#8a8f98"),
        _g("Gold", "#fff3b0", "#c98a1b"),
        _g("Ink", "#1b1b2f", "#4a4e69"),
    )),
    ("Blues", (
        _g("Sky", "#e0f4ff", "#2f8fd8"),
        _g("Ocean", "#5bc0eb", "#0b3d91"),
        _g("Ice", "#ffffff", "#8fd3fe"),
        _g("Deep Sea", "#1e3c72", "#2a5298"),
        _g("Electric", "#00d2ff", "#3a47d5"),
        _g("Night", "#0f2027", "#2c5364"),
    )),
    ("Purples", (
        _g("Lavender", "#f3e7ff", "#9b6dd6"),
        _g("Violet", "#c471f5", "#6a11cb"),
        _g("Galaxy", "#7f5af0", "#16004d"),
        _g("Plum", "#e0aaff", "#5a189a"),
        _g("Mystic", "#a18cd1", "#fbc2eb"),
        _g("Royal", "#8e2de2", "#4a00e0"),
    )),
    ("Pinks", (
        _g("Blossom", "#ffe4ef", "#ff6fa8"),
        _g("Candy", "#ff9a9e", "#fecfef"),
        _g("Hot Pink", "#ff5ea8", "#b5179e"),
        _g("Peach Pink", "#ffd1dc", "#ff8fab"),
        _g("Flamingo", "#f78ca0", "#f9748f"),
        _g("Rose", "#ffc3d8", "#c9184a"),
    )),
    ("Reds", (
        _g("Fire", "#ffdd00", "#e52d27"),
        _g("Crimson", "#ff4b2b", "#8b0000"),
        _g("Blood", "#c31432", "#240b36"),
        _g("Cherry", "#eb3349", "#f45c43"),
        _g("Ember", "#ff7a59", "#7a1010"),
        _g("Wine", "#a4161a", "#3d0c11"),
    )),
    ("Oranges", (
        _g("Sunset", "#ffd166", "#ef476f"),
        _g("Orange", "#ffb347", "#ff6a00"),
        _g("Amber", "#ffe259", "#ffa751"),
        _g("Rust", "#f0932b", "#8c3b0c"),
        _g("Tangerine", "#ff9966", "#ff5e62"),
        _g("Autumn", "#f7b267", "#a83f12"),
    )),
    ("Greens", (
        _g("Mint", "#e3fff2", "#2ec4a0"),
        _g("Leaf", "#a8e063", "#56ab2f"),
        _g("Forest", "#5a9e3a", "#0b3d1f"),
        _g("Lime", "#f0ff7a", "#5bd43a"),
        _g("Jade", "#43e97b", "#038c7f"),
        _g("Toxic", "#d4fc79", "#1a7f37"),
    )),
    ("Yellows", (
        _g("Lemon", "#fffde1", "#f9d423"),
        _g("Sunshine", "#fff200", "#ff9f00"),
        _g("Honey", "#ffe8a3", "#d99a00"),
        _g("Butter", "#fffbd5", "#e6c229"),
        _g("Neon", "#faff00", "#b8ff00"),
        _g("Sand", "#f6e7c1", "#c2a36b"),
    )),
)


def valid_hex(value) -> bool:
    return isinstance(value, str) and bool(_HEX.match(value))


def load_custom(path: str) -> list[Gradient]:
    """The user's own gradients; a missing or damaged file is an empty list."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        start, end = entry.get("start"), entry.get("end")
        if valid_hex(start) and valid_hex(end):
            out.append(Gradient(str(entry.get("name") or "").strip() or f"{start} → {end}", start.lower(), end.lower()))
    return out


def save_custom(path: str, gradients: list[Gradient]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump([{"name": g.name, "start": g.start, "end": g.end} for g in gradients], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def add_custom(gradients: list[Gradient], start: str, end: str, name: str = "") -> list[Gradient]:
    """`gradients` with (start, end) added, unless the same pair is already there."""
    start, end = start.lower(), end.lower()
    if not (valid_hex(start) and valid_hex(end)):
        raise ValueError((start, end))
    if any(g.start == start and g.end == end for g in gradients):
        return list(gradients)
    return [*gradients, Gradient(name.strip() or f"{start} → {end}", start, end)]


def remove_custom(gradients: list[Gradient], index: int) -> list[Gradient]:
    return [g for i, g in enumerate(gradients) if i != index]
