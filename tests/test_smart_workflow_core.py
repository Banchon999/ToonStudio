"""Smart Workflow's decisions: which pages each step runs on, and which orders work."""

import subprocess
import sys

from types import SimpleNamespace

from core.smart_workflow import (
    DEFAULT_ORDER,
    EXTRACTED_KEY,
    normalise_order,
    page_evidence,
    pages_for,
    validate,
)


def blk(text="", translation=""):
    return SimpleNamespace(text=text, translation=translation)


class TestEvidence:
    def test_an_empty_page_has_nothing(self):
        assert not any(page_evidence({}, None).values())

    def test_each_step_reads_its_own_result(self):
        state = {"blk_list": [blk("안녕", "สวัสดี")], "brush_strokes": [{}],
                 "viewer_state": {"text_items_state": [{}]}, EXTRACTED_KEY: True}
        assert all(page_evidence(state, [{"bbox": [0, 0, 1, 1]}]).values())

    def test_a_cleaned_page_counts_as_segmented(self):
        # Clean consumes Segment's strokes: without this, every cleaned page
        # would be segmented again on the next run.
        ev = page_evidence({"blk_list": [blk("a")], "brush_strokes": []}, [{"bbox": [0, 0, 1, 1]}])
        assert ev["segment"] and ev["clean"]

    def test_blank_text_is_no_text(self):
        ev = page_evidence({"blk_list": [blk("  ", " ")]}, None)
        assert ev["detect"] and not ev["recognize"] and not ev["translate"]


class TestPagesFor:
    EV = {
        "p1": {"detect": True, "recognize": True, "translate": False},
        "p2": {"detect": True, "recognize": True, "translate": True},   # translated by hand
        "p3": {"detect": True, "recognize": False, "translate": False},
        "p4": {"detect": False},
    }

    def test_skips_done_pages_and_pages_missing_the_prerequisite(self):
        assert pages_for("translate", list(self.EV), self.EV) == ["p1"]
        assert pages_for("recognize", list(self.EV), self.EV) == ["p3"]
        assert pages_for("detect", list(self.EV), self.EV) == ["p4"]

    def test_a_skipped_page_is_never_touched(self):
        assert pages_for("detect", list(self.EV), self.EV, skipped={"p4"}) == []


class TestValidate:
    def test_the_default_order_is_valid(self):
        assert validate(DEFAULT_ORDER) == []

    def test_a_step_before_the_step_it_needs_is_refused(self):
        problems = validate(["translate", "detect", "recognize"])
        assert [p.step for p in problems if p.blocking] == ["translate"]

    def test_a_missing_prerequisite_is_fine(self):
        # It works on pages that already have it.
        assert validate(["translate", "render"]) == []

    def test_render_before_clean_is_only_a_warning(self):
        problems = validate(["segment", "render", "clean"])
        assert problems and not any(p.blocking for p in problems)

    def test_normalise_keeps_order_drops_unknown_and_adds_missing(self):
        got = normalise_order([["render", True], ["bogus", True], ["detect", False]])
        assert got[:2] == [("render", True), ("detect", False)]
        assert {s for s, _ in got} == set(DEFAULT_ORDER)


def test_core_imports_without_qt():
    code = "import sys, core.smart_workflow; sys.exit('PySide6' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], cwd=".").returncode == 0
