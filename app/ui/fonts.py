"""The bundled UI typeface (core/theme_tokens.UI_FONT_FAMILY).

Loaded once, right after the QApplication exists and before any widget is
styled. A missing or unreadable file is logged and skipped: the theme's
font-family list continues with the platform faces, so the app still draws
Thai — just not in the house face.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtGui import QFontDatabase

from core import theme_tokens

logger = logging.getLogger(__name__)

# app/ui -> app -> repository root (also the bundle root in a frozen build,
# where resources/ is added next to app/).
UI_FONT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "resources", "fonts", "ui")
)

_loaded: list[str] | None = None


def load_ui_fonts(font_dir: str = UI_FONT_DIR) -> list[str]:
    """Register the UI font files with Qt; returns the families that loaded."""
    global _loaded
    if _loaded is not None and font_dir == UI_FONT_DIR:
        return _loaded
    families: list[str] = []
    for name in theme_tokens.UI_FONT_FILES:
        path = os.path.join(font_dir, name)
        if not os.path.isfile(path):
            logger.warning("UI font missing: %s", path)
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id == -1:
            logger.warning("UI font could not be loaded: %s", path)
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in families:
                families.append(family)
    if font_dir == UI_FONT_DIR:
        _loaded = families
    return families


# ---------------------------------------------------------------------------
# Fonts on the user's computer, loaded every start.
#
# Imported fonts are copied into <user data>/fonts, and folders the user adds
# in Settings > Text Rendering are read where they are (nothing copied). Both
# used to be loaded only when a saved style asked for a family by name, so an
# imported font was missing from every font list after a restart — "I have to
# import it again every time".

FONT_EXTENSIONS = (".ttf", ".ttc", ".otf", ".woff", ".woff2")
FONT_FOLDERS_KEY = "fonts/folders"

_registered: dict[str, list[str]] = {}  # font file → its families


def font_files_in(folder: str) -> list[str]:
    """Every font file under `folder`, subfolders included, in a stable order."""
    found: list[str] = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            if name.lower().endswith(FONT_EXTENSIONS) and not name.startswith("."):
                found.append(os.path.join(root, name))
    return found


def register_font_file(path: str) -> list[str]:
    """Register one font file with Qt (once); returns its families."""
    key = os.path.normcase(os.path.abspath(path))
    if key in _registered:
        return _registered[key]
    font_id = QFontDatabase.addApplicationFont(path)
    families = list(QFontDatabase.applicationFontFamilies(font_id)) if font_id != -1 else []
    if font_id == -1:
        logger.warning("Font could not be loaded: %s", path)
    _registered[key] = families
    return families


def load_font_folder(folder: str) -> list[str]:
    """Register every font under `folder`; returns the families, in order."""
    families: list[str] = []
    if not folder or not os.path.isdir(folder):
        return families
    for path in font_files_in(folder):
        for family in register_font_file(path):
            if family not in families:
                families.append(family)
    return families


def _settings():
    from PySide6.QtCore import QSettings

    return QSettings("ComicLabs", "ComicTranslate")


def font_folders() -> list[str]:
    """The font folders the user added in Settings, as stored."""
    value = _settings().value(FONT_FOLDERS_KEY, [])
    if isinstance(value, str):  # one entry comes back as a plain string on some platforms
        value = [value] if value else []
    return [str(v) for v in (value or []) if str(v).strip()]


def set_font_folders(folders: list[str]) -> None:
    unique: list[str] = []
    for folder in folders:
        if folder and folder not in unique:
            unique.append(folder)
    _settings().setValue(FONT_FOLDERS_KEY, unique)


def load_user_fonts() -> list[str]:
    """Imported fonts and every font folder from Settings; call once at start."""
    from app.ui.main_window.constants import user_font_path

    families: list[str] = []
    for folder in [user_font_path, *font_folders()]:
        for family in load_font_folder(folder):
            if family not in families:
                families.append(family)
    if families:
        logger.info("Loaded %d font families from the font folders", len(families))
    return families
