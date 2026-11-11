"""A second window to review a finished chapter while the first translates.

The app is single-instance, and a project opened while a chapter queue runs
used to load over the chapter being translated. It now opens in a review
window: a second process started with --review, which keeps its own recovery
slot and starts no queue.
"""

import os
import re
from pathlib import Path

import pytest

from core import chapter_queue as cq
from core import review_window as rw

ROOT = Path(__file__).resolve().parent.parent


def test_the_flag_and_the_command():
    assert rw.is_review(["comic.py", "--review", "a.ctpr"])
    assert not rw.is_review(["comic.py", "a.ctpr"])
    assert not rw.is_review(["--review"])            # argv[0] is the program
    frozen = rw.launch_command("/p/ep 1.ctpr", executable="/app/ToonStudio.exe", frozen=True)
    assert frozen == ["/app/ToonStudio.exe", "--review", os.path.abspath("/p/ep 1.ctpr")]
    source = rw.launch_command("/p/ep 1.ctpr", executable="/usr/bin/python", frozen=False)
    assert source[0] == "/usr/bin/python" and source[1].endswith("comic.py")
    assert os.path.isfile(source[1])
    assert source[2:] == ["--review", os.path.abspath("/p/ep 1.ctpr")]


def test_comic_py_keeps_a_review_window_out_of_the_single_instance_handover():
    text = (ROOT / "comic.py").read_text(encoding="utf-8")
    # It neither forwards its project to the first window nor listens for it…
    assert "if not review_mode and _try_forward_to_existing_instance" in text
    assert "if not review_mode and not server.listen(server_name)" in text
    # …and on exit must not remove the first window's server name.
    cleanup = text[text.index("server.close()"):]
    assert re.search(r"if not review_mode:\s+QLocalServer\.removeServer", cleanup)
    # A project opened while the first window translates goes to a review window.
    handler = text[text.index("def request_open_project"):text.index("def request_activate")]
    assert handler.index("is_busy_translating()") < handler.index("thread_load_project")
    assert "open_review_window(norm)" in handler


@pytest.fixture
def window(qapp, monkeypatch):
    import controller as controller_mod

    launched, said = [], []

    class FakePopen:
        def __init__(self, command, **kwargs):
            launched.append(command)

        def poll(self):
            return None

    import subprocess
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    from app.ui.messages import Messages
    monkeypatch.setattr(Messages, "show_review_opening", staticmethod(lambda parent, name: said.append(("open", name))))
    monkeypatch.setattr(Messages, "show_review_refused", staticmethod(lambda parent, name: said.append(("no", name))))
    made = []

    def make(**kwargs):
        win = controller_mod.ComicTranslate(**kwargs)
        made.append(win)
        return win

    yield make, launched, said
    for win in made:
        win._skip_close_prompt = True
        win.close()


def test_a_finished_chapter_opens_in_a_second_window_and_the_running_one_does_not(window, tmp_path):
    make, launched, said = window
    win = make()
    out = str(tmp_path)
    chapters = cq.make_chapters([str(tmp_path / "ep 1"), str(tmp_path / "ep 2")])
    for chapter in chapters:
        Path(cq.project_path(out, chapter)).write_bytes(b"x")
    queue = win.chapter_queue_ctrl
    queue.chapters, queue.output_dir, queue._index, queue.running = chapters, out, 1, True
    try:
        assert win.is_busy_translating()
        assert win.open_review_window(cq.project_path(out, chapters[0]))
        assert launched[-1][-2:] == ["--review", cq.project_path(out, chapters[0])]
        # The chapter being translated: two windows saving one file would
        # overwrite each other.
        assert not win.open_review_window(cq.project_path(out, chapters[1]))
        assert not win.open_review_window(str(tmp_path / "missing.ctpr"))
        assert len(launched) == 1
        assert [kind for kind, _ in said] == ["open", "no", "no"]

        # The queue window's own button follows the same rule.
        dialog = win.open_chapter_queue()
        dialog.chapters = chapters
        chapters[0].status, chapters[1].status = cq.DONE, cq.RUNNING
        assert dialog.reviewable_project(0) == cq.project_path(out, chapters[0])
        assert dialog.reviewable_project(1) is None
    finally:
        queue.running = False


def test_a_review_window_keeps_to_itself(window):
    make, launched, said = window
    win = make(review_mode=True)
    # Its own crash-recovery slot: writing or clearing the main one would
    # lose the checkpoint of the window that is translating.
    assert os.path.basename(win.project_ctrl._recovery_project_path()) == rw.RECOVERY_NAME
    # No chapter queue from here.
    assert win.open_chapter_queue() is None
    assert win.chapter_queue_nav_button.isHidden() and win.chapter_queue_button.isHidden()
    # And it says what it is, whatever sets the title later.
    win.setWindowTitle("ep 1.ctpr[*]")
    assert win.windowTitle().startswith("ep 1.ctpr[*] — ")
    win.setWindowTitle(win.windowTitle())
    assert win.windowTitle().count("—") == 1


def test_an_ordinary_window_keeps_the_main_recovery_slot(window):
    make, launched, said = window
    win = make()
    assert os.path.basename(win.project_ctrl._recovery_project_path()) == "project_recovery.ctpr"
    assert not win.review_mode and not win.is_busy_translating()
