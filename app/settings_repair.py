"""Remove stored settings this build can no longer read, before any are used.

`text_rendering/direction` was saved as a Python enum (core.enums.
LayoutDirection), which QSettings stores as a pickled PySide object. PySide
6.12 refuses to unpickle anything but builtin types, and it reports that in
the wrong place: the bad key reads as None, and the RuntimeError is raised by
whichever read happens first. At startup that was `text_rendering/color`, "Error during UI initialization" was logged, and the
app closed itself — on the first start after any clean exit.

Values are saved as plain ints now (ProjectController.process_group); this
drops what an earlier version left behind. Nothing reads `direction` back, so
removing it loses nothing.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)


def unreadable_keys(settings: QSettings) -> list[str]:
    """Keys whose stored value cannot be deserialised by this PySide.

    The failure is not raised at the key it belongs to: the bad key reads as
    None, and a RuntimeError is raised once by whichever read comes first.
    So: read everything, note whether an error came up at all, and if one did,
    the keys that read as None are the ones behind it.
    """
    failed = False
    empty: list[str] = []
    for key in settings.allKeys():
        value = None
        for _attempt in range(2):
            try:
                value = settings.value(key)
                break
            except RuntimeError:
                failed = True
        if value is None:
            empty.append(key)
    return empty if failed else []


def repair_settings() -> list[str]:
    # The storage identity is spelled out, as everywhere (tests/test_brand.py):
    # renaming it would silently reset every existing user's settings.
    settings = QSettings("ComicLabs", "ComicTranslate")
    try:
        bad = unreadable_keys(settings)
    except Exception:
        logger.exception("Could not check the stored settings")
        return []
    for key in bad:
        settings.remove(key)
        logger.warning("Removed a stored setting this version cannot read: %s", key)
    if bad:
        settings.sync()
    return bad
