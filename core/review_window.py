"""A second window for reviewing a finished project while the first is busy.

The app is single-instance: a second launch hands its project to the window
already open, which while a chapter queue or a batch is running would load it
over the chapter being translated. A *review window* is a second process
started with `--review <project.ctpr>`: it skips the single-instance
hand-over, so a finished chapter can be read and edited while the queue works
on the next one. Qt-free; `comic.py` and `controller.py` do the Qt side.

What a review window leaves alone, because the first window owns it:
- the crash-recovery slot (it has its own, `RECOVERY_NAME`);
- the chapter queue (it cannot start one);
- the single-instance server (it neither asks nor answers).
"""

from __future__ import annotations

import os
import sys

REVIEW_FLAG = "--review"
#: The review window's own crash-recovery checkpoint, beside the main one.
RECOVERY_NAME = "project_recovery_review.ctpr"


def is_review(argv: list[str]) -> bool:
    return REVIEW_FLAG in argv[1:]


def launch_command(project_path: str, executable: str | None = None,
                   frozen: bool | None = None, script: str | None = None) -> list[str]:
    """The command that opens `project_path` in a review window.

    A frozen build is its own executable; from source it is the interpreter
    running comic.py.
    """
    executable = executable or sys.executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    project_path = os.path.abspath(project_path)
    if frozen:
        return [executable, REVIEW_FLAG, project_path]
    script = script or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "comic.py")
    return [executable, script, REVIEW_FLAG, project_path]


def same_file(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    norm = lambda p: os.path.normcase(os.path.abspath(p))  # noqa: E731
    return norm(a) == norm(b)
