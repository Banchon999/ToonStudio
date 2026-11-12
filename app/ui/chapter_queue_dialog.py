"""The chapter queue window: list the chapters, choose where they go, press Start.

Non-modal, so the editor stays visible behind it while chapters run; the
status column follows `ChapterQueueController.chapter_changed`. Folders and
archives can be dropped onto the list. Settings persist under `chapter_queue/`.
"""

from __future__ import annotations

import os

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QSettings

from core import chapter_queue as cq
from app.controllers.chapter_queue import MODE_BATCH, MODE_SMART

SETTINGS_GROUP = "chapter_queue"


def status_label(status: str) -> str:
    # Spelled out each time: lupdate misfiles an aliased translate().
    if status == cq.PENDING:
        return QtCore.QCoreApplication.translate("ChapterQueueDialog", "Waiting")
    if status == cq.RUNNING:
        return QtCore.QCoreApplication.translate("ChapterQueueDialog", "Working…")
    if status == cq.DONE:
        return QtCore.QCoreApplication.translate("ChapterQueueDialog", "Done")
    if status == cq.REVIEW:
        return QtCore.QCoreApplication.translate("ChapterQueueDialog", "Done — review")
    if status == cq.FAILED:
        return QtCore.QCoreApplication.translate("ChapterQueueDialog", "Failed")
    if status == cq.SKIPPED:
        return QtCore.QCoreApplication.translate("ChapterQueueDialog", "Already done")
    if status == cq.STOPPED:
        return QtCore.QCoreApplication.translate("ChapterQueueDialog", "Stopped")
    return status


class ChapterQueueDialog(QtWidgets.QDialog):
    COL_NAME, COL_SOURCE, COL_PAGES, COL_STATUS = range(4)

    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.main = main
        self.ctrl = main.chapter_queue_ctrl
        self.chapters: list[cq.Chapter] = list(self.ctrl.chapters) if self.ctrl.running else []
        self._filling = False

        self.setWindowTitle(self.tr("Chapter Queue"))
        self.setModal(False)
        self.setAcceptDrops(True)
        self.resize(860, 560)

        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(self.tr(
            "Add chapters — a folder of images, a CBZ/ZIP/PDF, or a series folder whose "
            "subfolders are chapters. They are translated one after another; each is saved "
            "as its own project in the output folder, ready to review."))
        note.setWordWrap(True)
        layout.addWidget(note)

        add_row = QtWidgets.QHBoxLayout()
        self.add_folder_button = QtWidgets.QPushButton(self.tr("Add Folder…"), self)
        self.add_folder_button.setToolTip(self.tr(
            "A chapter folder, or a series folder: each subfolder (or CBZ/ZIP/PDF) in it "
            "becomes a chapter."))
        self.add_folder_button.clicked.connect(self._add_folder)
        self.add_files_button = QtWidgets.QPushButton(self.tr("Add Files…"), self)
        self.add_files_button.setToolTip(self.tr("CBZ, ZIP, PDF, EPUB… — each file is one chapter."))
        self.add_files_button.clicked.connect(self._add_files)
        self.up_button = QtWidgets.QPushButton(self.tr("Move Up"), self)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button = QtWidgets.QPushButton(self.tr("Move Down"), self)
        self.down_button.clicked.connect(lambda: self._move(1))
        self.remove_button = QtWidgets.QPushButton(self.tr("Remove"), self)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button = QtWidgets.QPushButton(self.tr("Clear"), self)
        self.clear_button.clicked.connect(self._clear)
        for button in (self.add_folder_button, self.add_files_button):
            add_row.addWidget(button)
        add_row.addStretch(1)
        for button in (self.up_button, self.down_button, self.remove_button, self.clear_button):
            add_row.addWidget(button)
        layout.addLayout(add_row)

        self.table = QtWidgets.QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels([
            self.tr("Chapter"), self.tr("Source"), self.tr("Pages"), self.tr("Status"),
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_NAME, QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_SOURCE, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_PAGES, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_STATUS, QtWidgets.QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(self.COL_NAME, 200)
        self.table.setColumnWidth(self.COL_STATUS, 220)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        form = QtWidgets.QFormLayout()
        self.mode_combo = QtWidgets.QComboBox(self)
        self.mode_combo.addItem(self.tr("Automatic — every step on every page"), MODE_BATCH)
        self.mode_combo.addItem(self.tr("Smart Workflow — your steps, in your order"), MODE_SMART)
        form.addRow(self.tr("Run with"), self.mode_combo)

        out_row = QtWidgets.QHBoxLayout()
        self.output_edit = QtWidgets.QLineEdit(self)
        self.output_edit.setPlaceholderText(self.tr("Where the projects and translated pages go"))
        self.output_browse = QtWidgets.QPushButton(self.tr("Browse"), self)
        self.output_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(self.output_browse)
        form.addRow(self.tr("Output folder"), out_row)

        self.export_combo = QtWidgets.QComboBox(self)
        for label, value in (
            (self.tr("Images in a folder per chapter"), "folder"),
            (self.tr("CBZ per chapter"), "cbz"),
            (self.tr("ZIP per chapter"), "zip"),
            (self.tr("PDF per chapter"), "pdf"),
            (self.tr("Project only"), "none"),
        ):
            self.export_combo.addItem(label, value)
        form.addRow(self.tr("Translated pages"), self.export_combo)

        self.psd_check = QtWidgets.QCheckBox(self.tr(
            "Also export PSD for editing (a \"<chapter>-PSD\" folder per chapter)"), self)
        self.psd_check.setToolTip(self.tr(
            "One PSD per page with the translation as editable text layers, written as soon as "
            "each chapter finishes: review and fix it in Photoshop or Photopea while the next "
            "chapter translates."))
        form.addRow("", self.psd_check)

        self.skip_done_check = QtWidgets.QCheckBox(self.tr(
            "Skip chapters an earlier run already finished"), self)
        self.skip_done_check.setToolTip(self.tr(
            "Run the same queue again after stopping it, or after the app closed, and only "
            "the unfinished chapters run. With Smart Workflow an interrupted chapter carries on "
            "from its saved project."))
        form.addRow("", self.skip_done_check)
        layout.addLayout(form)

        bottom = QtWidgets.QHBoxLayout()
        self.summary_label = QtWidgets.QLabel(self)
        bottom.addWidget(self.summary_label, 1)
        self.start_button = QtWidgets.QPushButton(self.tr("Start"), self)
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self._start)
        self.stop_button = QtWidgets.QPushButton(self.tr("Stop"), self)
        self.stop_button.setToolTip(self.tr("Stop after saving what the current chapter has so far"))
        self.stop_button.clicked.connect(self.ctrl.cancel)
        self.review_button = QtWidgets.QPushButton(self.tr("Open for Review"), self)
        self.review_button.setToolTip(self.tr(
            "Open the selected finished chapter to read and edit it. While the queue is "
            "running it opens in a second window, and the queue carries on."))
        self.review_button.clicked.connect(self._review_selected)
        self.close_button = QtWidgets.QPushButton(self.tr("Close"), self)
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.review_button)
        bottom.addWidget(self.start_button)
        bottom.addWidget(self.stop_button)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)

        self._load_settings()
        self.ctrl.chapter_changed.connect(self._on_chapter_changed)
        self.ctrl.queue_finished.connect(self._on_queue_finished)
        self._fill_table()
        self._update_buttons()

    # --- settings -------------------------------------------------------------

    def _settings(self) -> QSettings:
        return QSettings("ComicLabs", "ComicTranslate")

    def _load_settings(self) -> None:
        s = self._settings()
        s.beginGroup(SETTINGS_GROUP)
        default_mode = MODE_SMART if self.main.smart_radio.isChecked() else MODE_BATCH
        mode = s.value("mode", default_mode)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(mode)))
        self.output_edit.setText(str(s.value("output_dir", "") or ""))
        export = s.value("export_format", "folder")
        self.export_combo.setCurrentIndex(max(0, self.export_combo.findData(export)))
        self.skip_done_check.setChecked(str(s.value("skip_done", "true")).lower() != "false")
        self.psd_check.setChecked(str(s.value("export_psd", "false")).lower() == "true")
        s.endGroup()

    def _save_settings(self) -> None:
        s = self._settings()
        s.beginGroup(SETTINGS_GROUP)
        s.setValue("mode", self.mode_combo.currentData())
        s.setValue("output_dir", self.output_edit.text().strip())
        s.setValue("export_format", self.export_combo.currentData())
        s.setValue("skip_done", "true" if self.skip_done_check.isChecked() else "false")
        s.setValue("export_psd", "true" if self.psd_check.isChecked() else "false")
        s.endGroup()

    # --- the list ---------------------------------------------------------------

    def add_sources(self, paths: list[str]) -> int:
        """Queue every chapter `paths` hold; returns how many were added."""
        sources: list[str] = []
        for path in paths:
            sources.extend(cq.find_chapters(path))
        added = cq.make_chapters(sources, self.chapters)
        self.chapters.extend(added)
        self._fill_table()
        if not self.output_edit.text().strip() and self.chapters:
            first = self.chapters[0].source
            parent = os.path.dirname(first if os.path.isfile(first) else os.path.normpath(first))
            self.output_edit.setText(os.path.join(parent, "translated"))
        return len(added)

    def _add_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, self.tr("Add Chapter or Series Folder"))
        if folder and not self.add_sources([folder]):
            QtWidgets.QMessageBox.information(
                self, self.tr("Chapter Queue"),
                self.tr("No chapters were found there (no images, and no subfolders or archives "
                        "with images)."))

    def _add_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in cq.ARCHIVE_EXTENSIONS)
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, self.tr("Add Chapter Files"), "", f"{self.tr('Chapters')} ({patterns})")
        if files:
            self.add_sources(files)

    def _selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _move(self, step: int) -> None:
        rows = self._selected_rows()
        if not rows or (step < 0 and rows[0] == 0) or (step > 0 and rows[-1] == len(self.chapters) - 1):
            return
        for row in (rows if step < 0 else reversed(rows)):
            self.chapters[row], self.chapters[row + step] = self.chapters[row + step], self.chapters[row]
        self._fill_table()
        self.table.clearSelection()
        flags = (QtCore.QItemSelectionModel.SelectionFlag.Select
                 | QtCore.QItemSelectionModel.SelectionFlag.Rows)
        for row in rows:
            self.table.selectionModel().select(self.table.model().index(row + step, 0), flags)

    def _remove_selected(self) -> None:
        for row in reversed(self._selected_rows()):
            del self.chapters[row]
        self._fill_table()

    def _clear(self) -> None:
        self.chapters.clear()
        self._fill_table()

    def _fill_table(self) -> None:
        self._filling = True
        try:
            self.table.setRowCount(len(self.chapters))
            for row, chapter in enumerate(self.chapters):
                name = QtWidgets.QTableWidgetItem(chapter.name)
                source = QtWidgets.QTableWidgetItem(chapter.source)
                source.setToolTip(chapter.source)
                pages = QtWidgets.QTableWidgetItem(str(chapter.pages) if chapter.pages else "")
                status = QtWidgets.QTableWidgetItem()
                for item in (source, pages, status):
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, self.COL_NAME, name)
                self.table.setItem(row, self.COL_SOURCE, source)
                self.table.setItem(row, self.COL_PAGES, pages)
                self.table.setItem(row, self.COL_STATUS, status)
                self._show_status(row)
        finally:
            self._filling = False
        self._update_summary()
        self._update_buttons()

    def _show_status(self, row: int) -> None:
        chapter = self.chapters[row]
        item = self.table.item(row, self.COL_STATUS)
        if item is None:
            return
        text = status_label(chapter.status)
        if chapter.detail:
            text = f"{text}: {chapter.detail}"
        item.setText(text)
        item.setToolTip(text)

    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._filling or item.column() != self.COL_NAME:
            return
        row = item.row()
        others = {c.name for i, c in enumerate(self.chapters) if i != row}
        name = cq.unique_name(cq.chapter_stem(item.text()) if item.text().strip() else self.chapters[row].name,
                              others)
        self.chapters[row].name = name
        if item.text() != name:
            self._filling = True
            item.setText(name)
            self._filling = False

    def _update_summary(self) -> None:
        self.summary_label.setText(self.tr("{0} chapter(s)").format(len(self.chapters)))

    def _update_buttons(self) -> None:
        running = self.ctrl.running
        for widget in (self.add_folder_button, self.add_files_button, self.up_button, self.down_button,
                       self.remove_button, self.clear_button, self.mode_combo, self.output_edit,
                       self.output_browse, self.export_combo, self.skip_done_check, self.psd_check):
            widget.setEnabled(not running)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers if running else
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        self.start_button.setEnabled(not running and bool(self.chapters))
        self.stop_button.setEnabled(running)

    # --- run ----------------------------------------------------------------------

    def _browse_output(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, self.tr("Choose Output Folder"), self.output_edit.text().strip() or os.path.expanduser("~"))
        if folder:
            self.output_edit.setText(folder)

    def _start(self) -> None:
        if not self.chapters:
            return
        output_dir = self.output_edit.text().strip()
        if not output_dir:
            QtWidgets.QMessageBox.warning(self, self.tr("Chapter Queue"), self.tr("Choose an output folder."))
            return
        sources = {os.path.normcase(os.path.abspath(c.source)) for c in self.chapters}
        if os.path.normcase(os.path.abspath(output_dir)) in sources:
            QtWidgets.QMessageBox.warning(self, self.tr("Chapter Queue"), self.tr(
                "The output folder is one of the chapters. Choose another folder."))
            return
        if not self.main._confirm_start_new_project():
            return
        self._save_settings()
        if not self.ctrl.start(
            self.chapters, output_dir,
            export_format=self.export_combo.currentData(),
            mode=self.mode_combo.currentData(),
            skip_done=self.skip_done_check.isChecked(),
            export_psd=self.psd_check.isChecked(),
        ):
            QtWidgets.QMessageBox.warning(self, self.tr("Chapter Queue"), self.tr(
                "The queue did not start. Check the settings the message named, or that the "
                "output folder can be created."))
            return
        self._update_buttons()

    def reviewable_project(self, row: int) -> str | None:
        """The saved project of the chapter in `row`, unless it is being translated."""
        if not (0 <= row < len(self.chapters)):
            return None
        chapter = self.chapters[row]
        if chapter.status in (cq.RUNNING, cq.PENDING):
            return None
        output_dir = self.ctrl.output_dir if self.ctrl.chapters is self.chapters and self.ctrl.output_dir \
            else self.output_edit.text().strip()
        if not output_dir:
            return None
        path = cq.project_path(os.path.abspath(os.path.expanduser(output_dir)), chapter)
        return path if os.path.isfile(path) else None

    def _review_selected(self) -> None:
        rows = self._selected_rows()
        path = self.reviewable_project(rows[0]) if rows else None
        if not path:
            QtWidgets.QMessageBox.information(self, self.tr("Chapter Queue"), self.tr(
                "Select a chapter that has finished. The one being translated can be opened "
                "once it is done."))
            return
        if self.main.is_busy_translating():
            self.main.open_review_window(path)
        elif self.main._confirm_start_new_project():
            self.main.project_ctrl.thread_load_project(path)

    def _on_chapter_changed(self, row: int) -> None:
        if self.ctrl.chapters is not self.chapters or not (0 <= row < len(self.chapters)):
            return
        pages = self.table.item(row, self.COL_PAGES)
        if pages is not None:
            pages.setText(str(self.chapters[row].pages) if self.chapters[row].pages else "")
        self._show_status(row)
        if self.chapters[row].status == cq.RUNNING:
            self.table.scrollToItem(self.table.item(row, self.COL_NAME))

    def _on_queue_finished(self, _stopped: bool) -> None:
        self._update_buttons()

    # --- drag and drop --------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if not self.ctrl.running and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.add_sources(paths)
            event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        # Closing the window does not stop a running queue; the editor's
        # Cancel button or reopening this window and pressing Stop does.
        self._save_settings()
        super().closeEvent(event)
