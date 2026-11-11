"""Chapter queue: translate many chapters one after another, unattended.

For each chapter in turn the real window loads it (or the project an
interrupted run left for it), runs it with Automatic (batch) or Smart
Workflow exactly as the run button would, saves `<output>/<name>.ctpr`,
exports the translated pages, and moves on. The user comes back to a folder
of projects to review — each is also on Recent.

Everything is chained through callbacks on the GUI thread (the task runner's
queue, the run's own finished hooks), never by waiting: a chapter's batch
calls `on_run_finished` from `ComicTranslate.on_batch_process_finished`, and
Smart Workflow from `SmartWorkflowController._finish`. While the queue runs,
those two skip their per-run toasts, which would otherwise stack up one per
chapter.

Which folders are chapters, file names and resume are Qt-free in
`core/chapter_queue.py`.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6 import QtCore

from core import chapter_queue as cq
from core.i18n import translate

if TYPE_CHECKING:
    from controller import ComicTranslate

logger = logging.getLogger(__name__)

# Two chapters failing in a row is a setting or an account problem (a key,
# credit, a model id), not the chapters: stop instead of failing the rest.
MAX_FAILURES_IN_A_ROW = 2
# How long to wait for the first page to reach the canvas after loading.
DISPLAY_WAIT_MS = 20000
DISPLAY_POLL_MS = 100

MODE_BATCH = "batch"
MODE_SMART = "smart"


class ChapterQueueController(QtCore.QObject):
    chapter_changed = QtCore.Signal(int)     # row of the chapter whose status changed
    queue_finished = QtCore.Signal(bool)     # True when it stopped early

    def __init__(self, main: ComicTranslate) -> None:
        super().__init__(main)
        self.main = main
        self.chapters: list[cq.Chapter] = []
        self.output_dir = ""
        self.export_format = "folder"
        self.mode = MODE_BATCH
        self.skip_done = True
        self.export_psd = False
        self.running = False
        self.cancel_requested = False
        self._index = -1
        self._failures_in_a_row = 0
        self._step_failed = False
        self._run_result: dict = {}
        self._previous_project: str | None = None
        self._display_timer = QtCore.QTimer(self)
        self._display_timer.setInterval(DISPLAY_POLL_MS)
        self._display_timer.timeout.connect(self._poll_display)
        self._display_waited = 0

    # --- public ------------------------------------------------------------

    def start(self, chapters: list[cq.Chapter], output_dir: str, export_format: str = "folder",
              mode: str = MODE_BATCH, skip_done: bool = True, export_psd: bool = False) -> bool:
        if self.running or not chapters:
            return False
        output_dir = os.path.abspath(os.path.expanduser(output_dir or ""))
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError:
            logger.exception("Chapter queue: cannot create %s", output_dir)
            return False
        if not self._preflight(mode):
            return False
        self.chapters = chapters
        self.output_dir = output_dir
        self.export_format = export_format if export_format in cq.EXPORT_FORMATS else "folder"
        self.mode = mode
        self.skip_done = skip_done
        self.export_psd = bool(export_psd)
        self.running, self.cancel_requested = True, False
        self._failures_in_a_row = 0
        self._previous_project = None
        self._index = -1
        for row, chapter in enumerate(self.chapters):
            if chapter.status != cq.PENDING:
                chapter.status, chapter.detail = cq.PENDING, ""
                self.chapter_changed.emit(row)
        self._set_busy(True)
        self._next()
        return True

    def _preflight(self, mode: str) -> bool:
        """The settings every chapter will need, checked once before the first.

        Each check shows its own message, as the run buttons do; a key or a
        font missing at chapter 1 would be missing at chapter 20 too.
        """
        main = self.main
        if mode == MODE_SMART:
            from app.controllers.smart_workflow import load_order
            from core.smart_workflow import validate
            from app.ui.messages import Messages
            steps = [s for s, enabled in load_order() if enabled]
            blocking = [p for p in validate(steps) if p.blocking]
            if blocking or not steps:
                Messages.show_smart_workflow_invalid(main, "; ".join(p.message for p in blocking))
                return False
            return main.smart_ctrl._preflight(steps)
        from app import validation
        return bool(validation.validate_settings(main, main.t_combo.currentText()))

    def cancel(self) -> None:
        """Stop after saving what the current chapter has so far."""
        if not self.running:
            return
        self.cancel_requested = True
        self._status(translate("ChapterQueue", "Chapter queue: stopping…"))
        if self.main.smart_ctrl.running:
            self.main.smart_ctrl.cancel()
        elif getattr(self.main, "_batch_active", False):
            self.main.cancel_current_task()

    def on_run_finished(self, stopped: bool = False, failed: bool = False, review: int = 0) -> None:
        """Called by the batch or Smart Workflow when a chapter's run ends."""
        if not self.running or self._current() is None:
            return
        self._run_result = {"stopped": stopped, "failed": failed, "review": review}
        # Let the run's own finishing (button states, released models) settle
        # before the save is queued behind it.
        QtCore.QTimer.singleShot(0, self._save)

    # --- the chain ------------------------------------------------------------

    def _current(self) -> cq.Chapter | None:
        return self.chapters[self._index] if 0 <= self._index < len(self.chapters) else None

    def _set_status(self, status: str, detail: str = "") -> None:
        chapter = self._current()
        if chapter is None:
            return
        chapter.status, chapter.detail = status, detail
        self.chapter_changed.emit(self._index)
        if status != cq.PENDING:
            try:
                cq.save_progress(self.output_dir, chapter)
            except OSError:
                logger.exception("Chapter queue: could not record progress")

    def _next(self) -> None:
        if self.cancel_requested:
            return self._finish()
        progress = cq.load_progress(self.output_dir)
        while self._index + 1 < len(self.chapters):
            self._index += 1
            chapter = self.chapters[self._index]
            if self.skip_done and cq.already_done(self.output_dir, chapter, progress):
                chapter.status = cq.SKIPPED
                chapter.detail = translate("ChapterQueue", "finished in an earlier run")
                self.chapter_changed.emit(self._index)
                continue
            return self._load(chapter)
        return self._finish()

    def _load(self, chapter: cq.Chapter) -> None:
        self._step_failed = False
        self._run_result = {}
        target = cq.project_path(self.output_dir, chapter)
        resume = cq.resumable_project(self.output_dir, chapter) if self.mode == MODE_SMART else None
        self._set_status(cq.RUNNING)
        self._status(translate("ChapterQueue", "Chapter {0}/{1}: {2} — loading").format(
            self._index + 1, len(self.chapters), chapter.name))
        if resume:
            # Smart Workflow carries on where the interrupted run stopped:
            # only the steps a page still lacks run again.
            logger.info("Chapter queue: resuming %s from %s", chapter.name, resume)
            self.main.project_ctrl.thread_load_project(resume, on_success=self._loaded)
            return
        paths = [chapter.source] if chapter.is_archive else cq.images_in(chapter.source)
        if not paths:
            return self._chapter_failed(translate("ChapterQueue", "no images found"))
        # Set before loading: with auto-save on, the loader keeps the current
        # project file, and the previous chapter's must never receive this one.
        self.main.project_file = target
        self.main.image_ctrl.thread_load_images(paths)
        self.main.run_finish_only(self._loaded)

    def _loaded(self) -> None:
        chapter = self._current()
        if chapter is None:
            return
        if self._previous_project and self._previous_project != cq.project_path(self.output_dir, chapter):
            from app.projects.project_state import close_state_store
            close_state_store(self._previous_project)
        self._previous_project = None
        if not self.main.image_files:
            return self._chapter_failed(translate("ChapterQueue", "could not be opened"))
        target = cq.project_path(self.output_dir, chapter)
        self.main.project_file = target
        self.main.setWindowTitle(f"{os.path.basename(target)}[*]")
        chapter.pages = len(self.main.image_files)
        self.chapter_changed.emit(self._index)
        if self.cancel_requested:
            return self._save()
        # The first page is shown by an operation queued after the load;
        # the run starts once it is on the canvas.
        self._display_waited = 0
        self._display_timer.start()

    def _poll_display(self) -> None:
        self._display_waited += DISPLAY_POLL_MS
        shown = self.main.webtoon_mode or self.main.image_viewer.hasPhoto()
        if not shown and self._display_waited < DISPLAY_WAIT_MS:
            return
        self._display_timer.stop()
        self._start_run()

    def _start_run(self) -> None:
        chapter = self._current()
        self._status(translate("ChapterQueue", "Chapter {0}/{1}: {2} — translating").format(
            self._index + 1, len(self.chapters), chapter.name))
        main = self.main
        if self.mode == MODE_SMART:
            main.smart_radio.setChecked(True)
            main.smart_mode_selected()
            if not main.smart_ctrl.start():
                return self._run_refused()
        else:
            main.automatic_radio.setChecked(True)
            main.batch_mode_selected()
            main.start_batch_process()
            if not getattr(main, "_batch_active", False):
                return self._run_refused()
        # The run's own busy state turned the run button back on; keep the
        # queue's Stop on the cancel button.
        self._set_busy(True)

    def _run_refused(self) -> None:
        """The run did not start (it showed why): the next chapter would not either."""
        self.cancel_requested = True
        self._chapter_failed(translate("ChapterQueue", "the run did not start — check the settings"))

    def _save(self) -> None:
        chapter = self._current()
        if chapter is None:
            return
        main = self.main
        target = cq.project_path(self.output_dir, chapter)
        main.project_file = target
        main.project_ctrl.save_current_state()
        start_revision = main._dirty_revision
        failed = {"error": ""}

        def on_error(error_tuple):
            _exctype, value, _tb = error_tuple
            failed["error"] = str(value)
            logger.error("Chapter queue: saving %s failed: %s", target, value)

        def on_finished():
            if failed["error"]:
                self._step_failed = True
                return self._chapter_finished(translate("ChapterQueue", "could not be saved: {0}").format(
                    failed["error"]))
            if main._dirty_revision == start_revision:
                main.set_project_clean()
            main.project_ctrl.clear_recovery_checkpoint()
            main.project_ctrl.add_recent_project(target)
            self._export()

        self._status(translate("ChapterQueue", "Chapter {0}/{1}: {2} — saving").format(
            self._index + 1, len(self.chapters), chapter.name))
        main.run_threaded(main.project_ctrl.save_project, None, on_error, on_finished, target)

    def _export(self) -> None:
        chapter = self._current()
        destination = cq.export_path(self.output_dir, chapter, self.export_format)
        if self._run_result.get("failed"):
            return self._chapter_finished()
        if not destination:
            return self._export_psd()
        main = self.main
        plan = [{
            "output_path": destination,
            "page_indices": list(range(len(main.image_files))),
            "folder": self.export_format == "folder",
        }]
        pages_state = main.project_ctrl._build_all_pages_current_state()
        failed = {"error": ""}

        def on_error(error_tuple):
            _exctype, value, _tb = error_tuple
            failed["error"] = str(value)
            logger.error("Chapter queue: exporting %s failed: %s", destination, value)

        def on_finished():
            if failed["error"]:
                self._step_failed = True
                return self._chapter_finished(translate("ChapterQueue", "could not be exported: {0}").format(
                    failed["error"]))
            self._export_psd()

        self._status(translate("ChapterQueue", "Chapter {0}/{1}: {2} — exporting").format(
            self._index + 1, len(self.chapters), chapter.name))
        main.run_threaded(main.project_ctrl.save_and_make_worker, None, on_error, on_finished,
                          plan, pages_state)

    def _export_psd(self) -> None:
        """Editable PSDs of the chapter, one per page, when asked for.

        Written right after the chapter, so a finished chapter can be reviewed
        and fixed in Photoshop or Photopea while the queue works on the next.
        """
        if not self.export_psd:
            return self._chapter_finished()
        from app.controllers.psd_exporter import export_psd_pages, warm_font_cache

        chapter = self._current()
        main = self.main
        destination = cq.psd_path(self.output_dir, chapter)
        pages_state = main.project_ctrl._build_all_pages_current_state()
        # The fonts are resolved here, on the GUI thread: the worker must
        # never read the font database (Qt's font objects are thread-local).
        try:
            warm_font_cache(pages_state)
        except Exception:
            logger.debug("Chapter queue: could not pre-resolve PSD fonts", exc_info=True)
        failed = {"error": ""}

        def write():
            pages = main.project_ctrl._gather_psd_pages(pages_state)
            export_psd_pages(output_folder=destination, pages=pages, bundle_name=chapter.name)

        def on_error(error_tuple):
            _exctype, value, _tb = error_tuple
            failed["error"] = str(value)
            logger.error("Chapter queue: PSD export of %s failed: %s", destination, value)

        def on_finished():
            if failed["error"]:
                self._step_failed = True
                return self._chapter_finished(translate("ChapterQueue", "PSD could not be exported: {0}").format(
                    failed["error"]))
            self._chapter_finished()

        self._status(translate("ChapterQueue", "Chapter {0}/{1}: {2} — exporting PSD").format(
            self._index + 1, len(self.chapters), chapter.name))
        main.run_threaded(write, None, on_error, on_finished)

    def _chapter_finished(self, error: str = "") -> None:
        result = self._run_result
        if error or result.get("failed"):
            return self._chapter_failed(error or translate("ChapterQueue", "a step failed — open the project"))
        self._failures_in_a_row = 0
        if result.get("stopped") or self.cancel_requested:
            self._set_status(cq.STOPPED, translate("ChapterQueue", "stopped — saved as far as it got"))
        elif result.get("review"):
            self._set_status(cq.REVIEW, translate("ChapterQueue", "{0} page(s) skipped — see its Report").format(
                result["review"]))
        else:
            self._set_status(cq.DONE)
        self._previous_project = cq.project_path(self.output_dir, self._current())
        self._next()

    def _chapter_failed(self, detail: str) -> None:
        self._set_status(cq.FAILED, detail)
        self._failures_in_a_row += 1
        if self._failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
            self.cancel_requested = True
        project = cq.project_path(self.output_dir, self._current())
        self._previous_project = project if os.path.isfile(project) else None
        self._next()

    def _finish(self) -> None:
        stopped = self.cancel_requested
        self.running = False
        self.cancel_requested = False
        self._display_timer.stop()
        # Chapters never reached stay pending; say so in the list.
        for row, chapter in enumerate(self.chapters):
            if chapter.status == cq.RUNNING:
                chapter.status = cq.STOPPED
                self.chapter_changed.emit(row)
        self._set_busy(False)
        self._status("")
        counts = {s: sum(1 for c in self.chapters if c.status == s)
                  for s in (cq.DONE, cq.REVIEW, cq.FAILED, cq.SKIPPED)}
        from app.ui.messages import Messages
        Messages.show_chapter_queue_done(self.main, counts[cq.DONE], counts[cq.REVIEW],
                                         counts[cq.FAILED], counts[cq.SKIPPED], self.output_dir,
                                         stopped=stopped)
        self.queue_finished.emit(stopped)

    # --- UI ------------------------------------------------------------------

    def _status(self, text: str) -> None:
        bar = getattr(self.main, "editor_status_bar", None)
        if bar is not None and hasattr(bar, "set_workflow_status"):
            bar.set_workflow_status(text, running=self.running)

    def _set_busy(self, busy: bool) -> None:
        main = self.main
        main.translate_button.setEnabled(not busy)
        main.cancel_button.setEnabled(True)
        main.webtoon_toggle.setEnabled(not busy)
        button = getattr(main, "chapter_queue_button", None)
        if button is not None:
            button.setEnabled(not busy)
