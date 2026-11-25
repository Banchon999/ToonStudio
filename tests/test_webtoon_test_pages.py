"""The Korean webtoon test pages and their ground truth stay usable together."""

import json
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent / "data" / "webtoon_ko"
KINDS = {"narration", "speech", "thought", "sfx", "sign", "system"}


def _truth():
    return json.loads((HERE / "pages.json").read_text(encoding="utf-8"))


def test_every_page_has_ground_truth_and_every_entry_has_an_image():
    truth = _truth()
    images = sorted(p.name for p in HERE.glob("*.png"))
    assert images == sorted(truth["pages"]) == ["page_01.png", "page_02.png", "page_03.png"]


def test_every_image_decodes_as_a_tall_rgb_page():
    for name in _truth()["pages"]:
        array = np.asarray(Image.open(HERE / name).convert("RGB"))
        height, width, _ = array.shape
        assert 700 <= width <= 1000 and height > 2 * width, name
        assert array.std() > 20, f"{name} is not blank"


def test_entries_are_well_formed():
    truth = _truth()
    for name, entries in truth["pages"].items():
        assert entries, name
        for entry in entries:
            assert entry["kind"] in KINDS, (name, entry)
            assert entry["text"].strip(), (name, entry)
            speaker = entry.get("speaker")
            if speaker is not None:
                assert speaker in truth["speakers"], (name, entry)
            if "as_drawn" in entry:
                assert entry["as_drawn"] != entry["text"], (name, entry)
