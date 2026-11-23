"""Outline presets: a text item's outline (and extra strokes) in one click (Qt-free).

A style preset (`text_presets.py`) carries a whole look; these carry only the
edge — colour, width and any stroke layers outside it — so a group's usual
"white with a black edge" is one pick, without touching the font or fill.

Built-ins are read-only and stored by their English name; the user's own live
in ``<user data>/outline_presets.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .paths import get_user_data_dir

PRESET_FILE = "outline_presets.json"


@dataclass
class OutlinePreset:
    name: str
    color: str
    width: float
    #: Stroke layers outside the outline, innermost first: (colour, width).
    strokes: list[tuple[str, float]] = field(default_factory=list)
    builtin: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "color": self.color, "width": self.width,
                "strokes": [[c, w] for c, w in self.strokes]}

    @classmethod
    def from_dict(cls, data: dict) -> "OutlinePreset | None":
        try:
            name = str(data["name"]).strip()
            color = str(data["color"])
            width = float(data["width"])
            strokes = [(str(c), float(w)) for c, w in (data.get("strokes") or [])]
        except (KeyError, TypeError, ValueError):
            return None
        if not name or width <= 0:
            return None
        return cls(name, color, width, strokes)


BUILT_IN: tuple[OutlinePreset, ...] = (
    OutlinePreset("Thin black", "#000000", 1.5, builtin=True),
    OutlinePreset("Thick black", "#000000", 3.0, builtin=True),
    OutlinePreset("Thin white", "#ffffff", 1.5, builtin=True),
    OutlinePreset("Thick white", "#ffffff", 3.0, builtin=True),
    OutlinePreset("White, black edge", "#ffffff", 2.5, [("#000000", 2.0)], builtin=True),
    OutlinePreset("Black, white edge", "#000000", 2.5, [("#ffffff", 2.5)], builtin=True),
)


class OutlinePresetStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(get_user_data_dir(), PRESET_FILE)
        self._user: list[OutlinePreset] = []
        self.load()

    def load(self) -> None:
        self._user = []
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        for raw in data.get("presets", []) if isinstance(data, dict) else []:
            preset = OutlinePreset.from_dict(raw) if isinstance(raw, dict) else None
            if preset is not None and not self.is_builtin_name(preset.name):
                self._user.append(preset)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "presets": [p.to_dict() for p in self._user]}, handle,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    @staticmethod
    def is_builtin_name(name: str) -> bool:
        return any(p.name.casefold() == name.strip().casefold() for p in BUILT_IN)

    def all(self) -> list[OutlinePreset]:
        return [*BUILT_IN, *self._user]

    def get(self, name: str) -> OutlinePreset | None:
        return next((p for p in self.all() if p.name == name), None)

    def put(self, preset: OutlinePreset) -> None:
        """Add or replace a user preset (never a built-in)."""
        if self.is_builtin_name(preset.name):
            raise ValueError("a built-in preset has that name")
        preset.builtin = False
        self._user = [p for p in self._user if p.name.casefold() != preset.name.casefold()] + [preset]
        self.save()

    def remove(self, name: str) -> bool:
        before = len(self._user)
        self._user = [p for p in self._user if p.name != name]
        if len(self._user) != before:
            self.save()
            return True
        return False
