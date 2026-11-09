"""A failed auto-save leaves the work unsaved, and says so.

The save worker emits `finished` after an error too, and auto-save's
`on_finished` took that as a save: it marked the project clean, deleted the
recovery checkpoint and put the file on the Recent list. In 3.3.0 every save
of a page with batch-rendered text failed (an outline colour stored as a hex
string), so auto-save "ran" all session, closing the app asked nothing, and
reopening the project from Recent showed it as it was before — no layers, no
translations. The failure itself was a log line only.
"""

import os
import time

import numpy as np
import pytest

from app.ui.messages import Messages


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    import controller as controller_mod

    win = controller_mod.ComicTranslate()
    page = tmp_path / "001.png"
    from PIL import Image
    Image.fromarray(np.full((40, 60, 3), 200, dtype=np.uint8)).save(page)
    win.image_files = [str(page)]
    win.project_file = str(tmp_path / "proj.ctpr")
    ctrl = win.project_ctrl
    monkeypatch.setattr(ctrl, "save_current_state", lambda: None)
    monkeypatch.setattr(
        win.settings_page, "get_export_settings",
        lambda: {"project_autosave_enabled": True, "project_autosave_interval_min": 3,
                 "project_autosave_folder": str(tmp_path)},
    )
    shown = []
    monkeypatch.setattr(Messages, "show_autosave_failed",
                        staticmethod(lambda parent, detail: shown.append(detail)))
    win._shown = shown
    yield win
    win._skip_close_prompt = True
    win.close()


def _wait_until_idle(qapp, ctrl, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if not ctrl._autosave_save_pending and not ctrl.main.task_runner_ctrl.is_processing_queue:
            # Let the queued finished callback run as well.
            for _ in range(5):
                qapp.processEvents()
                time.sleep(0.01)
            return
        time.sleep(0.01)
    raise AssertionError("auto-save did not finish")


def _autosave_with(window, qapp, monkeypatch, save):
    ctrl = window.project_ctrl
    ctrl._realtime_autosave_timer.stop()
    monkeypatch.setattr(ctrl, "save_project", save)
    window._manual_dirty = True
    ctrl.autosave_project(prefer_project_file=True)
    _wait_until_idle(qapp, ctrl)
    ctrl._realtime_autosave_timer.stop()


def test_a_failed_autosave_leaves_the_work_unsaved_and_the_recovery_file_in_place(
        window, qapp, monkeypatch):
    ctrl = window.project_ctrl
    recovery = ctrl._recovery_project_path()
    os.makedirs(os.path.dirname(recovery), exist_ok=True)
    with open(recovery, "wb") as f:
        f.write(b"earlier checkpoint")

    def broken_save(file_name):
        raise AttributeError("'str' object has no attribute 'name'")

    _autosave_with(window, qapp, monkeypatch, broken_save)

    assert window.has_unsaved_changes()          # closing will still ask to save
    assert os.path.exists(recovery)              # the checkpoint was not thrown away
    assert window.project_file not in [e.get("path") for e in ctrl.get_recent_projects()]
    assert len(window._shown) == 1 and "AttributeError" in window._shown[0]


def test_the_failure_is_said_once_until_a_save_works_again(window, qapp, monkeypatch):
    def broken_save(file_name):
        raise OSError("disk full")

    _autosave_with(window, qapp, monkeypatch, broken_save)
    _autosave_with(window, qapp, monkeypatch, broken_save)
    assert len(window._shown) == 1               # not a toast every 800 ms

    _autosave_with(window, qapp, monkeypatch, lambda file_name: None)
    assert not window.has_unsaved_changes()
    _autosave_with(window, qapp, monkeypatch, broken_save)
    assert len(window._shown) == 2               # a new failure after a good save is said again
