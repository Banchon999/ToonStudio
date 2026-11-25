"""Do the editor's panels come back after the app is closed and opened again?

Drives the real start-up (comic.main: splash, single-instance server, the
real window) on a real windowing system, not the offscreen platform, because
the offscreen tests passed while users still lost their panels. Each phase is
its own process, as a user's restart is:

    python scripts/probe_panels.py make   OUT_DIR           # a one-page project
    python scripts/probe_panels.py float  OUT_DIR           # open it, float panels, quit
    python scripts/probe_panels.py reopen OUT_DIR           # open it again, report
    python scripts/probe_panels.py home   OUT_DIR           # start on the home screen, open it, report

Every phase writes OUT_DIR/<phase>.json (each panel: floating, visible,
ticked in the Panels menu, geometry, on a screen) and OUT_DIR/<phase>.png
(the whole screen). .github/workflows/panel-probe.yml runs it on Windows.
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PHASE, OUT = sys.argv[1], os.path.abspath(sys.argv[2])
os.makedirs(OUT, exist_ok=True)
PROJECT = os.path.join(OUT, "probe.ctpr")
FLOATED = ("dock_layers", "dock_color")


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line, flush=True)
    with open(os.path.join(OUT, "probe.log"), "a", encoding="utf-8") as handle:
        handle.write(f"[{PHASE}] {line}\n")


def make_project() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    import controller

    win = controller.ComicTranslate()
    win.image_ctrl.thread_load_images([os.path.join(ROOT, "docs", "images", "demo", "page.png")])
    deadline = time.time() + 60
    while time.time() < deadline and not win.image_files:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(40):
        app.processEvents()
        time.sleep(0.02)
    win.project_ctrl.save_project(PROJECT)
    log("project", PROJECT, os.path.getsize(PROJECT))
    win._skip_close_prompt = True
    win.close()


def report(win, name: str) -> dict:
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QGuiApplication

    screens = [s.availableGeometry() for s in QGuiApplication.screens()]
    stack = getattr(win, "_center_stack", None)
    data = {
        "platform": QGuiApplication.platformName(),
        "page": type(stack.currentWidget()).__name__ if stack else None,
        "window": list(win.frameGeometry().getRect()),
        "window_maximized": win.isMaximized(),
        "screens": [list(g.getRect()) for g in screens],
        "saved_state_bytes": len(QSettings("ComicLabs", "ComicTranslate").value("editor/dock_state") or b""),
        "page_hidden": sorted(getattr(win, "_page_hidden_docks", ())),
        "panels": {},
    }
    for key, dock in win.panel_docks.items():
        frame = dock.frameGeometry()
        global_rect = dock.geometry()
        if not dock.isFloating():
            top_left = dock.mapToGlobal(dock.rect().topLeft())
            global_rect.moveTopLeft(top_left)
        data["panels"][key] = {
            "floating": dock.isFloating(),
            "visible": dock.isVisible(),
            "hidden": dock.isHidden(),
            "ticked": dock.toggleViewAction().isChecked(),
            "size": [dock.width(), dock.height()],
            "global": list(global_rect.getRect()),
            "on_screen": any(s.intersects(frame if dock.isFloating() else global_rect) for s in screens),
            "minimized": bool(dock.isFloating() and dock.isMinimized()),
            # A floating panel must belong to the main window: one that does not
            # is a window of its own, which keeps the app running once the main
            # window closes and is managed apart from it.
            "owned_by_main": bool(dock.isFloating() and dock.windowHandle() is not None
                                  and dock.windowHandle().transientParent() is win.windowHandle()),
            "tabbed_behind": bool(not dock.isFloating() and any(
                other.isVisible() for other in win.editor_docks.tabifiedDockWidgets(dock))),
        }
    with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)
    shot = QGuiApplication.primaryScreen().grabWindow(0)
    shot.save(os.path.join(OUT, f"{name}.png"))
    lost = [k for k, p in data["panels"].items()
            if p["ticked"] and not p["tabbed_behind"]
            and (not p["visible"] or not p["on_screen"] or p["size"][0] < 50)]
    unowned = [k for k, p in data["panels"].items() if p["floating"] and not p["owned_by_main"]]
    log(name, "page", data["page"], "floating", [k for k, p in data["panels"].items() if p["floating"]],
        "ticked but not seen", lost, "floating but not owned by the main window", unowned)
    return data


def drive(win) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def editor_up() -> bool:
        stack = getattr(win, "_center_stack", None)
        return bool(stack and stack.currentWidget() is win.main_content_widget and win.image_files)

    def when(condition, then, timeout=90.0, start=None):
        start = start or time.time()
        if condition():
            QTimer.singleShot(2500, then)  # let the layout and any deferred show settle
        elif time.time() - start > timeout:
            log("timed out waiting; page:", type(win._center_stack.currentWidget()).__name__)
            report(win, PHASE)
            QApplication.instance().quit()
        else:
            QTimer.singleShot(250, lambda: when(condition, then, timeout, start))

    def close():
        win._skip_close_prompt = True
        win.close()  # the real closeEvent, which saves the layout

    if PHASE == "float":
        def float_them():
            report(win, "float_before")
            screen = win.screen().availableGeometry()
            for i, key in enumerate(FLOATED):
                dock = win.panel_docks[key]
                dock.setFloating(True)
                dock.show()
                dock.move(screen.right() - 360, screen.top() + 80 + i * 380)
                dock.resize(340, 340)
            QTimer.singleShot(1500, lambda: (report(win, "float_after"), close()))
        when(editor_up, float_them)
    elif PHASE == "reopen":
        when(editor_up, lambda: (report(win, "reopen"), close()))
    elif PHASE == "home":
        def open_it():
            report(win, "home_start")
            win.project_ctrl.thread_load_project(PROJECT)
            when(editor_up, lambda: (report(win, "home"), close()))
        QTimer.singleShot(6000, open_it)


def _patch(controller) -> None:
    if os.environ.get("PROBE_WITHOUT_FIX"):
        # The code before panels were given an owner, to prove the probe sees
        # the fault on this desktop (panel-probe.yml runs it both ways).
        from app.ui.main_window.docks import DockMixin

        DockMixin.own_floating_panels = lambda self: None
        DockMixin._own_floating = lambda self, dock: False
        DockMixin.hide_floating_panels = lambda self: None
    original = controller.ComicTranslate.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: drive(self))

    controller.ComicTranslate.__init__ = init


class _PatchController:
    """Patches `controller` the moment comic.py imports it (importing it here
    first would create a QApplication before comic.main does)."""

    def find_spec(self, name, path=None, target=None):
        if name != "controller":
            return None
        import importlib.machinery

        sys.meta_path.remove(self)
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        loader = spec.loader
        exec_module = loader.exec_module

        def run(module):
            exec_module(module)
            _patch(module)

        loader.exec_module = run
        return spec


def run_app() -> None:
    sys.meta_path.insert(0, _PatchController())
    import comic

    sys.argv = ["comic.py"] + ([] if PHASE == "home" else [PROJECT])
    comic.main()


if __name__ == "__main__":
    if PHASE == "make":
        make_project()
    else:
        run_app()
