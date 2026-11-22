"""Font folders: fonts on the user's computer in every font list, every start.

Imported fonts are copied into <user data>/fonts and were only loaded when a
saved style asked for a family by name, so after a restart they were missing
from the font lists until imported again.
"""

import os
import shutil

import pytest
from PySide6.QtGui import QFontDatabase


def _a_font_file():
    from app.ui.fonts import UI_FONT_DIR

    for name in sorted(os.listdir(UI_FONT_DIR)):
        if name.lower().endswith((".ttf", ".otf")):
            return os.path.join(UI_FONT_DIR, name)
    pytest.skip("no bundled font to copy")


def test_a_folder_is_read_with_its_subfolders(qapp, tmp_path):
    from app.ui import fonts

    nested = tmp_path / "fonts" / "comic"
    nested.mkdir(parents=True)
    shutil.copy(_a_font_file(), nested / "MyFont.ttf")
    (nested / "readme.txt").write_text("x")
    assert fonts.font_files_in(str(tmp_path / "fonts")) == [str(nested / "MyFont.ttf")]
    families = fonts.load_font_folder(str(tmp_path / "fonts"))
    assert families and set(families) <= set(QFontDatabase.families())
    assert fonts.load_font_folder(str(tmp_path / "missing")) == []


def test_folders_are_remembered_and_loaded_at_start(qapp, tmp_path):
    from app.ui import fonts
    from app.ui.main_window.constants import user_font_path

    folder = tmp_path / "mine"
    folder.mkdir()
    shutil.copy(_a_font_file(), folder / "Other.ttf")
    imported = os.path.join(user_font_path, "Imported.ttf")
    shutil.copy(_a_font_file(), imported)
    try:
        fonts.set_font_folders([str(folder), str(folder)])
        assert fonts.font_folders() == [str(folder)]
        fonts._registered.clear()
        families = fonts.load_user_fonts()
        assert families, "the imported font and the folder's are loaded"
        keys = {os.path.normcase(os.path.abspath(p)) for p in (imported, str(folder / "Other.ttf"))}
        assert keys <= set(fonts._registered)
    finally:
        os.remove(imported)
        fonts.set_font_folders([])


def test_the_settings_box_adds_and_removes_folders(qapp, tmp_path):
    from app.ui import fonts
    from app.ui.settings.text_rendering_page import FontFoldersBox

    folder = tmp_path / "box"
    folder.mkdir()
    shutil.copy(_a_font_file(), folder / "Box.ttf")
    box = FontFoldersBox()
    try:
        loaded = box.add_folder(str(folder))
        assert loaded >= 1
        assert fonts.font_folders() == [str(folder)]
        assert str(loaded) in box.status.text()
        box.list.item(0).setSelected(True)
        box.remove_selected()
        assert fonts.font_folders() == []
    finally:
        fonts.set_font_folders([])
        box.deleteLater()
