"""What a crash-recovery checkpoint is a checkpoint *of* (Qt-free).

The checkpoint itself is a project file in the autosave folder. Beside it
goes a small JSON sidecar saying which project it came from, when, and how
many pages it holds — so the offer to restore can name the work, and a
restored project goes back to being the file it was instead of an untitled
copy the user has to find a home for again.

The lifecycle follows PhotoCraft's recovery store
(`crates/format/src/autosave.rs`, MIT OR Apache-2.0): a checkpoint is deleted
when its project is saved or deliberately closed, **never just because it
was restored** — a second crash before the next checkpoint must lose nothing.
The sidecar is written to a temporary file, flushed, and renamed over the old
one, so a crash mid-write leaves the previous sidecar, not half of a new one;
and a checkpoint with no readable sidecar is still a checkpoint.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass

#: A sidecar larger than this is not one of ours.
MAX_SIDECAR_BYTES = 1 << 20


@dataclass
class RecoveryInfo:
    #: Where the project was last saved, or "" if it never was.
    original_path: str = ""
    #: What to call it in the offer to restore.
    document_name: str = ""
    #: Seconds since the Unix epoch.
    saved_at: float = 0.0
    pages: int = 0


def sidecar_path(checkpoint: str) -> str:
    return os.path.splitext(checkpoint)[0] + ".json"


def sync_file(path: str) -> None:
    """Ask the OS to put `path`'s bytes on the disk. Best effort: a file
    system that cannot (some network shares) is no reason to fail a save."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_info(checkpoint: str, info: RecoveryInfo) -> None:
    """Publish the sidecar for `checkpoint`, replacing any earlier one whole."""
    target = sidecar_path(checkpoint)
    folder = os.path.dirname(target) or "."
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="recovery_tmp_", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(info), handle, ensure_ascii=False)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass


def read_info(checkpoint: str) -> RecoveryInfo:
    """The sidecar's contents, or what the checkpoint file alone tells: its
    modification time. Never raises — a crash during a project's very first
    checkpoint leaves no sidecar, and the checkpoint is still worth offering."""
    info = RecoveryInfo()
    try:
        info.saved_at = os.path.getmtime(checkpoint)
    except OSError:
        pass
    target = sidecar_path(checkpoint)
    try:
        if not os.path.isfile(target) or os.path.getsize(target) > MAX_SIDECAR_BYTES:
            return info
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return info
    if not isinstance(data, dict):
        return info
    if isinstance(data.get("original_path"), str):
        info.original_path = data["original_path"]
    if isinstance(data.get("document_name"), str):
        info.document_name = data["document_name"]
    if isinstance(data.get("pages"), int) and not isinstance(data.get("pages"), bool):
        info.pages = max(0, data["pages"])
    if isinstance(data.get("saved_at"), (int, float)) and not isinstance(data.get("saved_at"), bool):
        info.saved_at = float(data["saved_at"])
    return info


def new_info(original_path: str | None, pages: int) -> RecoveryInfo:
    original = os.path.abspath(original_path) if original_path else ""
    return RecoveryInfo(
        original_path=original,
        document_name=os.path.basename(original) if original else "",
        saved_at=time.time(),
        pages=int(pages),
    )


def remove(checkpoint: str) -> None:
    """Delete the checkpoint and its sidecar. The sidecar goes first: a
    checkpoint without one is still offered, a sidecar without one is litter."""
    for path in (sidecar_path(checkpoint), checkpoint):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
