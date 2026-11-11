"""Chapter queue: many chapters translated one after another, unattended.

Qt-free on purpose: which folders and files are chapters, what each chapter's
output is called, and which chapters an earlier run already finished are all
decided here, so `tests/test_chapter_queue_core.py` can check them without a
window. `app/controllers/chapter_queue.py` drives the real window through them.

A chapter is a folder of images (searched recursively, in natural order, as
"Open Folder" does) or one archive/document file (CBZ, ZIP, PDF, EPUB…), which
the window's file handler already knows how to unpack.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".avif")
ARCHIVE_EXTENSIONS = (
    ".cbr", ".cbz", ".cbt", ".cb7", ".zip", ".rar", ".7z", ".tar", ".pdf", ".epub",
)

# Where each chapter's result goes, beside its project file.
EXPORT_FORMATS = ("folder", "cbz", "zip", "pdf", "none")

PROGRESS_FILE = "chapter_queue.json"

# Statuses a chapter moves through in one run.
PENDING, RUNNING, DONE, REVIEW, FAILED, SKIPPED, STOPPED = (
    "pending", "running", "done", "review", "failed", "skipped", "stopped",
)


def natural_key(text: str) -> list:
    """'ตอนที่ 2' before 'ตอนที่ 10' — the order a person numbers chapters in."""
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", text)]


@dataclass
class Chapter:
    source: str            # a folder of images, or one archive/document file
    name: str              # output stem: <name>.ctpr, <name>.cbz, <name>/
    status: str = PENDING
    detail: str = ""       # why it failed, how many pages need a look…
    pages: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def is_archive(self) -> bool:
        return os.path.isfile(self.source) and self.source.lower().endswith(ARCHIVE_EXTENSIONS)


def images_in(folder: str) -> list[str]:
    """Every image under `folder`, subfolders included, in natural order."""
    paths: list[str] = []
    for root, dirs, files in os.walk(folder):
        dirs.sort(key=natural_key)
        for name in sorted(files, key=natural_key):
            if name.lower().endswith(IMAGE_EXTENSIONS) and not name.startswith("."):
                paths.append(os.path.join(root, name))
    return paths


def _has_direct_images(folder: str) -> bool:
    try:
        return any(
            entry.is_file() and entry.name.lower().endswith(IMAGE_EXTENSIONS)
            for entry in os.scandir(folder)
        )
    except OSError:
        return False


def find_chapters(path: str) -> list[str]:
    """The chapter sources `path` holds, in natural order.

    - an archive or document file is one chapter;
    - a folder with images directly inside it is one chapter (its
      subfolders are part of it, as with "Open Folder");
    - any other folder is a series: each subfolder that has images somewhere
      below it is a chapter, and so is each archive directly inside it.
    """
    path = os.path.normpath(path)
    if os.path.isfile(path):
        return [path] if path.lower().endswith(ARCHIVE_EXTENSIONS) else []
    if not os.path.isdir(path):
        return []
    if _has_direct_images(path):
        return [path]
    found: list[str] = []
    try:
        entries = sorted(os.scandir(path), key=lambda e: natural_key(e.name))
    except OSError:
        return []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if images_in(entry.path):
                found.append(os.path.normpath(entry.path))
        elif entry.is_file() and entry.name.lower().endswith(ARCHIVE_EXTENSIONS):
            found.append(os.path.normpath(entry.path))
    return found


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def chapter_stem(source: str) -> str:
    """A file name for a chapter's outputs, from its folder or file name."""
    base = os.path.basename(os.path.normpath(source))
    if os.path.isfile(source):
        base = os.path.splitext(base)[0]
    stem = _UNSAFE.sub("_", base).strip(" .")
    return stem or "chapter"


def unique_name(stem: str, taken: set[str]) -> str:
    """`stem`, or `stem (2)`, `stem (3)`… — compared without case (Windows)."""
    lowered = {t.casefold() for t in taken}
    name, n = stem, 2
    while name.casefold() in lowered:
        name = f"{stem} ({n})"
        n += 1
    return name


def make_chapters(sources: list[str], existing: list[Chapter] | None = None) -> list[Chapter]:
    """New chapters for `sources`, skipping ones already queued, with unique names."""
    existing = list(existing or [])
    queued = {os.path.normcase(os.path.normpath(c.source)) for c in existing}
    taken = {c.name for c in existing}
    added: list[Chapter] = []
    for source in sources:
        key = os.path.normcase(os.path.normpath(source))
        if key in queued:
            continue
        queued.add(key)
        name = unique_name(chapter_stem(source), taken)
        taken.add(name)
        added.append(Chapter(source=os.path.normpath(source), name=name))
    return added


def project_path(output_dir: str, chapter: Chapter) -> str:
    return os.path.join(output_dir, f"{chapter.name}.ctpr")


def export_path(output_dir: str, chapter: Chapter, export_format: str) -> str | None:
    """Where the translated pages go: a folder, an archive, or nowhere."""
    if export_format == "none":
        return None
    if export_format == "folder":
        return os.path.join(output_dir, chapter.name)
    return os.path.join(output_dir, f"{chapter.name}.{export_format}")


def psd_path(output_dir: str, chapter: Chapter) -> str:
    """The folder of editable PSDs, one per page, beside the chapter's other outputs.

    A folder of its own: with the "folder" export the chapter's images already
    fill <output>/<name>/, and a page's .png and .psd side by side read as two
    copies of one page.
    """
    return os.path.join(output_dir, f"{chapter.name}-PSD")


def page_psd_folder(original_path: str, archive_path: str | None = None) -> str:
    """Where an Automatic run writes one page's PSD: beside its chapter.

    A page from a folder goes to "<folder>-PSD" next to that folder, so a
    workspace with several chapter folders gets one PSD folder per chapter,
    named after it (the chapter queue's "<name>-PSD" too). A page unpacked
    from an archive goes beside the archive, "<archive name>-PSD". Such a
    folder holds no images, so find_chapters never takes it for a chapter.
    """
    if archive_path:
        stem = os.path.splitext(os.path.basename(archive_path))[0].strip() or "chapter"
        return os.path.join(os.path.dirname(archive_path), f"{stem}-PSD")
    folder = os.path.dirname(os.path.abspath(original_path))
    name = os.path.basename(folder) or "chapter"
    return os.path.join(os.path.dirname(folder), f"{name}-PSD")


# --- progress: which chapters an earlier run finished ------------------------

def _progress_file(output_dir: str) -> str:
    return os.path.join(output_dir, PROGRESS_FILE)


def load_progress(output_dir: str) -> dict[str, dict]:
    """{chapter name: {"source": …, "status": …}} from the output folder."""
    try:
        with open(_progress_file(output_dir), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    chapters = data.get("chapters") if isinstance(data, dict) else None
    return {k: v for k, v in (chapters or {}).items() if isinstance(v, dict)}


def save_progress(output_dir: str, chapter: Chapter) -> None:
    """Record how `chapter` ended; written to a temp file and renamed into place."""
    progress = load_progress(output_dir)
    progress[chapter.name] = {"source": chapter.source, "status": chapter.status,
                              "detail": chapter.detail}
    target = _progress_file(output_dir)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"chapters": progress}, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, target)


def already_done(output_dir: str, chapter: Chapter, progress: dict[str, dict] | None = None) -> bool:
    """Finished cleanly by an earlier run, from the same source, project still there.

    A chapter that ended with pages to review, failed or was stopped is run
    again; so is one whose project file has since been deleted.
    """
    progress = load_progress(output_dir) if progress is None else progress
    entry = progress.get(chapter.name)
    if not entry or entry.get("status") != DONE:
        return False
    same_source = os.path.normcase(os.path.normpath(str(entry.get("source", "")))) == \
        os.path.normcase(os.path.normpath(chapter.source))
    return same_source and os.path.isfile(project_path(output_dir, chapter))


def resumable_project(output_dir: str, chapter: Chapter) -> str | None:
    """A project an interrupted run left for `chapter`, to continue from.

    Only when an earlier run of this queue started it from the same source:
    a file of that name from anywhere else is not ours to open.
    """
    path = project_path(output_dir, chapter)
    if not os.path.isfile(path):
        return None
    entry = load_progress(output_dir).get(chapter.name)
    if not entry:
        return None
    same_source = os.path.normcase(os.path.normpath(str(entry.get("source", "")))) == \
        os.path.normcase(os.path.normpath(chapter.source))
    return path if same_source else None
