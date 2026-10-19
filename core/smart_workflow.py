"""Smart Workflow: which step runs next, on which pages (Qt-free).

Batch mode redoes every step on every page, so a translation fixed by hand
is overwritten by the next run. Smart Workflow runs one step across all
pages before the next, in an order the user chooses, and only on the pages
that do not have that step's result yet — read from the page itself, the way
the step bar does (`core/editor_state.py`), never from a "done" flag the user
could not see or clear. The one stored marker is the glossary extraction's,
which leaves nothing else behind on a page.

`app/controllers/smart_workflow.py` drives the steps; this decides them.
"""

from __future__ import annotations

from dataclasses import dataclass

STEPS = ("detect", "recognize", "extract", "translate", "segment", "clean", "render")
DEFAULT_ORDER = list(STEPS)

# Each step needs this one's result on the page first.
REQUIRES = {
    "recognize": "detect",
    "extract": "recognize",
    "translate": "recognize",
    "segment": "detect",
    "clean": "segment",     # Clean inpaints the strokes Segment leaves
    "render": "translate",
}

# Page state key the extract step sets on every page it read.
EXTRACTED_KEY = "glossary_extracted"


def page_evidence(state: dict | None, patches) -> dict[str, bool]:
    """Which steps a page has been through, from what is on it."""
    state = state or {}
    blocks = list(state.get("blk_list") or [])
    strokes = bool(state.get("brush_strokes"))
    cleaned = bool(patches)
    viewer = state.get("viewer_state") or {}
    return {
        "detect": bool(blocks),
        "recognize": any((getattr(b, "text", "") or "").strip() for b in blocks),
        "extract": bool(state.get(EXTRACTED_KEY)),
        "translate": any((getattr(b, "translation", "") or "").strip() for b in blocks),
        # Clean consumes the strokes, so a cleaned page has been segmented.
        "segment": strokes or cleaned,
        "clean": cleaned,
        "render": bool(viewer.get("text_items_state")),
    }


def pages_for(step: str, pages: list[str], evidence: dict[str, dict[str, bool]],
              skipped: set[str] | None = None) -> list[str]:
    """The pages `step` should run on: without its result, with its prerequisite.

    A page the user marked to skip is never touched. A page that already has
    the result keeps it — that is what protects hand-made edits.
    """
    skipped = skipped or set()
    need = REQUIRES.get(step)
    out = []
    for page in pages:
        if page in skipped:
            continue
        ev = evidence.get(page, {})
        if ev.get(step):
            continue
        if need and not ev.get(need):
            continue
        out.append(page)
    return out


@dataclass
class OrderProblem:
    step: str
    message: str
    blocking: bool = True


def validate(order: list[str]) -> list[OrderProblem]:
    """What is wrong with an order of enabled steps.

    A step placed before the step it needs is blocking only when that step
    is also in the run — otherwise it simply works on pages that already
    have the prerequisite. Rendering before cleaning draws over the original
    lettering, which is allowed but almost never wanted.
    """
    problems: list[OrderProblem] = []
    unknown = [s for s in order if s not in STEPS]
    for s in unknown:
        problems.append(OrderProblem(s, f"unknown step {s!r}"))
    if len(set(order)) != len(order):
        problems.append(OrderProblem("", "a step appears twice"))
    position = {s: i for i, s in enumerate(order)}
    for s in order:
        need = REQUIRES.get(s)
        if need in position and position[need] > position[s]:
            problems.append(OrderProblem(s, f"{s} must come after {need}"))
    if "render" in position and "clean" in position and position["render"] < position["clean"]:
        problems.append(OrderProblem("render", "render before clean draws over the original text",
                                     blocking=False))
    return problems


def normalise_order(saved) -> list[tuple[str, bool]]:
    """A saved [(step, enabled)] list made whole: unknown steps dropped,
    missing ones appended enabled in their default place order."""
    result: list[tuple[str, bool]] = []
    seen = set()
    for item in saved or []:
        try:
            step, enabled = item
        except (TypeError, ValueError):
            continue
        if step in STEPS and step not in seen:
            result.append((step, bool(enabled)))
            seen.add(step)
    for step in DEFAULT_ORDER:
        if step not in seen:
            result.append((step, True))
    return result
