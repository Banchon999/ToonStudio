"""Crash recovery keeps what it recovered until the work is really saved.

Three losses the old code allowed, each found by reading it beside
PhotoCraft's recovery store (which deletes an entry only when its document is
saved or closed):

* restoring deleted the checkpoint at once, so a second crash before the next
  checkpoint — up to the auto-save interval later — lost everything recovered;
* a restored project came back as an untitled "RecoveredProject", cut off
  from the file it was a newer copy of;
* starting the app by double-clicking the project, the natural thing to do
  after a crash, deleted the checkpoint without ever offering it.
"""

import json
import os
import time

import numpy as np
import pytest

from core import recovery


class TestSidecar:
    def test_it_round_trips(self, tmp_path):
        checkpoint = str(tmp_path / "project_recovery.ctpr")
        project = tmp_path / "ตอนที่ 12.ctpr"
        project.write_bytes(b"x")
        recovery.write_info(checkpoint, recovery.new_info(str(project), 24))
        info = recovery.read_info(checkpoint)
        assert info.original_path == str(project)
        assert info.document_name == "ตอนที่ 12.ctpr"
        assert info.pages == 24
        assert abs(info.saved_at - time.time()) < 60

    def test_a_checkpoint_with_no_sidecar_is_still_described(self, tmp_path):
        """A crash during a project's first checkpoint leaves no sidecar."""
        checkpoint = tmp_path / "project_recovery.ctpr"
        checkpoint.write_bytes(b"x")
        info = recovery.read_info(str(checkpoint))
        assert info.original_path == "" and info.pages == 0
        assert info.saved_at == pytest.approx(os.path.getmtime(checkpoint))

    @pytest.mark.parametrize("content", [
        "", "not json", "[1, 2]", '{"original_path": 5, "pages": "many", "saved_at": true}',
    ])
    def test_a_damaged_sidecar_is_ignored_not_fatal(self, tmp_path, content):
        checkpoint = tmp_path / "project_recovery.ctpr"
        checkpoint.write_bytes(b"x")
        (tmp_path / "project_recovery.json").write_text(content, encoding="utf-8")
        info = recovery.read_info(str(checkpoint))
        assert info.original_path == "" and info.pages == 0

    def test_writing_replaces_the_old_one_whole_and_leaves_no_temp_file(self, tmp_path):
        checkpoint = str(tmp_path / "project_recovery.ctpr")
        recovery.write_info(checkpoint, recovery.new_info(None, 3))
        recovery.write_info(checkpoint, recovery.new_info(None, 9))
        assert sorted(os.listdir(tmp_path)) == ["project_recovery.json"]
        assert json.loads((tmp_path / "project_recovery.json").read_text(encoding="utf-8"))["pages"] == 9

    def test_remove_takes_both_files_and_tolerates_neither(self, tmp_path):
        checkpoint = tmp_path / "project_recovery.ctpr"
        checkpoint.write_bytes(b"x")
        recovery.write_info(str(checkpoint), recovery.new_info(None, 1))
        recovery.remove(str(checkpoint))
        assert os.listdir(tmp_path) == []
        recovery.remove(str(checkpoint))            # nothing there: no error


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    import controller as controller_mod
    from PIL import Image

    win = controller_mod.ComicTranslate()
    page = tmp_path / "001.png"
    Image.fromarray(np.full((40, 60, 3), 200, dtype=np.uint8)).save(page)
    win._page = str(page)
    ctrl = win.project_ctrl
    monkeypatch.setattr(ctrl, "save_current_state", lambda: None)
    monkeypatch.setattr(
        win.settings_page, "get_export_settings",
        lambda: {"project_autosave_enabled": False, "project_autosave_interval_min": 3,
                 "project_autosave_folder": str(tmp_path)},
    )
    monkeypatch.setattr(ctrl, "_autosave_dir", lambda: str(tmp_path / "autosave"))
    os.makedirs(tmp_path / "autosave")
    yield win
    win._skip_close_prompt = True
    win.close()


def _run_now(window, monkeypatch, loaded_pages):
    """Make run_threaded synchronous, with a load that 'opens' loaded_pages."""
    ctrl = window.project_ctrl

    def run_threaded(func, on_result, on_error, on_finished, *args):
        try:
            result = func(*args)
            if on_result:
                on_result(result)
        except Exception as error:                   # as the worker reports it
            if on_error:
                on_error((type(error), error, ""))
        if on_finished:
            on_finished()

    monkeypatch.setattr(window, "run_threaded", run_threaded)
    monkeypatch.setattr(ctrl, "load_project", lambda path: None)
    monkeypatch.setattr(ctrl, "load_state_to_ui", lambda result: None)

    def update_ui():
        window.image_files = list(loaded_pages)

    monkeypatch.setattr(ctrl, "update_ui_from_project", update_ui)


def test_a_checkpoint_says_which_project_it_is_of(window, monkeypatch, tmp_path):
    ctrl = window.project_ctrl
    project = tmp_path / "series.ctpr"
    project.write_bytes(b"x")
    window.image_files = [window._page]
    window.project_file = str(project)
    window._manual_dirty = True
    _run_now(window, monkeypatch, [window._page])
    monkeypatch.setattr(ctrl, "save_project", lambda path: open(path, "wb").write(b"checkpoint"))

    ctrl.autosave_project(prefer_project_file=False)     # the interval timer's call

    checkpoint = ctrl._recovery_project_path()
    assert os.path.exists(checkpoint)
    info = recovery.read_info(checkpoint)
    assert info.original_path == str(project) and info.pages == 1
    assert window.has_unsaved_changes()                  # a checkpoint is not a save


def test_restoring_keeps_the_checkpoint_and_the_project_it_belongs_to(window, monkeypatch, tmp_path):
    ctrl = window.project_ctrl
    project = tmp_path / "series.ctpr"
    project.write_bytes(b"older save")
    checkpoint = ctrl._recovery_project_path()
    with open(checkpoint, "wb") as handle:
        handle.write(b"checkpoint")
    recovery.write_info(checkpoint, recovery.new_info(str(project), 1))
    _run_now(window, monkeypatch, [window._page])

    ctrl.restore_recovery_project()

    assert os.path.exists(checkpoint)                    # a second crash loses nothing
    assert window.project_file == str(project)           # Save goes to its own file
    assert "series.ctpr" in window.windowTitle()
    assert window.has_unsaved_changes()


def test_a_project_whose_file_is_gone_is_restored_untitled(window, monkeypatch, tmp_path):
    ctrl = window.project_ctrl
    checkpoint = ctrl._recovery_project_path()
    with open(checkpoint, "wb") as handle:
        handle.write(b"checkpoint")
    recovery.write_info(checkpoint, recovery.new_info(str(tmp_path / "moved away.ctpr"), 1))
    _run_now(window, monkeypatch, [window._page])

    ctrl.restore_recovery_project()

    assert window.project_file is None
    assert os.path.exists(checkpoint)


def test_saving_the_restored_project_removes_the_checkpoint(window, monkeypatch, tmp_path):
    ctrl = window.project_ctrl
    project = tmp_path / "series.ctpr"
    project.write_bytes(b"older save")
    checkpoint = ctrl._recovery_project_path()
    with open(checkpoint, "wb") as handle:
        handle.write(b"checkpoint")
    recovery.write_info(checkpoint, recovery.new_info(str(project), 1))
    _run_now(window, monkeypatch, [window._page])
    ctrl.restore_recovery_project()
    monkeypatch.setattr(ctrl, "save_project", lambda path: None)

    ctrl.run_save_proj(str(project))

    assert not os.path.exists(checkpoint)
    assert not os.path.exists(recovery.sidecar_path(checkpoint))


def test_opening_a_project_at_startup_offers_the_checkpoint_first(window, monkeypatch, tmp_path):
    """Declining without discarding leaves it for next time."""
    from PySide6 import QtWidgets

    ctrl = window.project_ctrl
    checkpoint = ctrl._recovery_project_path()
    with open(checkpoint, "wb") as handle:
        handle.write(b"checkpoint")
    recovery.write_info(checkpoint, recovery.new_info(str(tmp_path / "series.ctpr"), 7))
    seen = {}

    def fake_exec(box):
        seen["text"] = box.informativeText()
        seen["buttons"] = [b.text() for b in box.buttons()]
        return 0

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QtWidgets.QMessageBox, "clickedButton", lambda box: None)

    restored = ctrl.prompt_restore_recovery_if_available(opening=str(tmp_path / "series.ctpr"))

    assert restored is False
    assert "series.ctpr" in seen["text"] and "7" in seen["text"]
    assert len(seen["buttons"]) == 3
    assert os.path.exists(checkpoint)


def test_startup_does_not_clear_the_checkpoint_when_it_opens_a_project():
    """comic.py offers the checkpoint before opening, and opens without
    clearing it."""
    import inspect
    import comic
    source = inspect.getsource(comic)
    assert "prompt_restore_recovery_if_available(opening=opening)" in source
    assert "request_open_project(opening, clear_recovery=False)" in source
