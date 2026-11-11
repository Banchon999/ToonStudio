"""PSDs written page by page while an Automatic run is still going.

With Settings > Export > "Export PSD of each page as soon as it is
translated", every page the batch finishes (`render_state_ready`) is written
as an editable PSD to "<its folder>-PSD" beside its chapter
(`core.chapter_queue.page_psd_folder`). In a workspace with several chapter
folders that is one PSD folder per chapter, filling up while the batch moves
on, so a finished chapter can be reviewed and fixed in Photoshop or Photopea
without waiting for the rest.

The writes go one at a time on the shared thread pool, not through
`run_threaded`: that queue is busy with the batch itself until it ends (the
per-page auto-save works around it the same way). The page's state and its
fonts are read here on the GUI thread first, as every PSD export must.
The chapter queue writes its own per-chapter PSDs, so this stays out of its way.
"""

from __future__ import annotations

import logging
import os
from collections import deque
from typing import TYPE_CHECKING

from PySide6 import QtCore

from app.thread_worker import GenericWorker
from core.chapter_queue import page_psd_folder

if TYPE_CHECKING:
    from controller import ComicTranslate

logger = logging.getLogger(__name__)


class BatchPsdExporter(QtCore.QObject):
    def __init__(self, main: ComicTranslate) -> None:
        super().__init__(main)
        self.main = main
        self._pending: deque[tuple[str, dict]] = deque()
        self._busy = False
        self._workers: list[GenericWorker] = []   # kept alive until they finish
        self.written: list[str] = []              # every PSD written, for the tests
        self.failures: list[tuple[str, str]] = []

    # --- when ------------------------------------------------------------------

    def enabled(self) -> bool:
        try:
            settings = self.main.settings_page.get_export_settings()
        except Exception:
            return False
        if not settings.get("export_psd"):
            return False
        queue = getattr(self.main, "chapter_queue_ctrl", None)
        if queue is not None and queue.running:
            return False  # the queue writes its own, per chapter
        return bool(getattr(self.main, "_batch_active", False))

    def destination(self, image_path: str) -> str:
        """The page's PSD path, beside the chapter it came from."""
        original = self.main.path_originals.get(image_path, image_path)
        archive = None
        for info in getattr(self.main.file_handler, "archive_info", []) or []:
            if image_path in (info.get("extracted_images") or []):
                archive = info.get("archive_path")
                break
        folder = page_psd_folder(original, archive)
        stem = os.path.splitext(os.path.basename(original))[0] or "page"
        return os.path.join(folder, f"{stem}.psd")

    # --- what --------------------------------------------------------------------

    def on_page_done(self, image_path: str) -> None:
        if not self.enabled() or image_path not in self.main.image_files:
            return
        from app.controllers.psd_exporter import warm_font_cache

        # The page as the batch left it, read now on the GUI thread.
        state = self.main.project_ctrl._build_all_pages_current_state()
        try:
            warm_font_cache({image_path: state[image_path]})
        except Exception:
            logger.debug("Batch PSD: could not pre-resolve fonts", exc_info=True)
        self._pending.append((image_path, state))
        self._next()

    def _next(self) -> None:
        if self._busy or not self._pending:
            return
        image_path, state = self._pending.popleft()
        target = self.destination(image_path)
        self._busy = True
        worker = GenericWorker(self._write, image_path, state, target)
        self._workers.append(worker)
        failed = {"error": ""}

        def on_error(error_tuple):
            _exctype, value, _tb = error_tuple
            failed["error"] = str(value)

        def on_finished():
            if worker in self._workers:
                self._workers.remove(worker)
            self._busy = False
            if failed["error"]:
                logger.error("Batch PSD: %s could not be written: %s", target, failed["error"])
                self.failures.append((target, failed["error"]))
            else:
                self.written.append(target)
            self._next()

        worker.signals.error.connect(lambda err: QtCore.QTimer.singleShot(0, self, lambda: on_error(err)))
        worker.signals.finished.connect(lambda: QtCore.QTimer.singleShot(0, self, on_finished))
        self.main.threadpool.start(worker)

    def _write(self, image_path: str, state: dict, target: str) -> None:
        from app.controllers.psd_exporter import export_psd_pages

        pages = self.main.project_ctrl._gather_psd_pages(state, only_paths={image_path})
        if not pages:
            return
        export_psd_pages(output_folder=os.path.dirname(target), pages=pages,
                         bundle_name=os.path.basename(os.path.dirname(target)),
                         single_file_path=target)

    def idle(self) -> bool:
        return not self._busy and not self._pending
