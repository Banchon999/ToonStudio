"""A setting stored as a pickled Python object must not stop the app starting.

Found while starting a second window: every clean exit wrote
text_rendering/direction as a core.enums.LayoutDirection, PySide 6.12 refuses
to unpickle it, and the error surfaced on the next QSettings read — the
window's own construction — so the app logged "Error during UI
initialization" and closed.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WRITE_OLD = """
    from PySide6.QtCore import QSettings, QCoreApplication
    app = QCoreApplication([])
    from core.enums import LayoutDirection
    s = QSettings("ComicLabs", "ComicTranslate")
    s.beginGroup("text_rendering")
    s.setValue("direction", LayoutDirection.Auto)   # what 3.4.1 and earlier wrote
    s.setValue("color", "#112233")
    s.endGroup()
    s.sync()
"""

READ_BACK = """
    from PySide6.QtCore import QSettings, QCoreApplication
    app = QCoreApplication([])
    {repair}
    s = QSettings("ComicLabs", "ComicTranslate")
    s.beginGroup("text_rendering")
    s.value("direction")
    print("color=" + str(s.value("color", "#000000")))
"""


def _run(code, config):
    # A process of its own: a value is only unpickled by a process that did
    # not write it, which is exactly the restart this is about.
    import os
    env = dict(os.environ, XDG_CONFIG_HOME=str(config), HOME=str(config), QT_QPA_PLATFORM="offscreen")
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


def test_an_old_pickled_setting_is_removed_and_the_rest_still_read(tmp_path):
    assert _run(WRITE_OLD, tmp_path).returncode == 0
    repaired = _run(READ_BACK.format(
        repair="from app.settings_repair import repair_settings; print('removed', repair_settings())"), tmp_path)
    assert repaired.returncode == 0, repaired.stderr
    assert "color=#112233" in repaired.stdout
    # Nothing else is touched, and a second start finds nothing to remove.
    again = _run(READ_BACK.format(
        repair="from app.settings_repair import repair_settings; print('removed', repair_settings())"), tmp_path)
    assert "removed []" in again.stdout and "color=#112233" in again.stdout


def test_enums_are_saved_as_plain_values(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from app.controllers.projects import ProjectController
    from core.enums import LayoutDirection

    class Main:
        class settings_page:
            class ui:
                value_mappings = {}

    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    controller = ProjectController.__new__(ProjectController)
    controller.main = Main
    controller.process_group("text_rendering",
                             {"direction": LayoutDirection.RightToLeft, "color": "#000"}, settings)
    settings.sync()
    text = (tmp_path / "s.ini").read_text(encoding="utf-8")
    assert "direction=1" in text and "PyObjectWrapper" not in text
