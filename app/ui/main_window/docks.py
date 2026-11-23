"""The editor's panels as dockable windows, as in Photoshop and PhotoCraft.

The canvas sits in a nested QMainWindow (`editor_docks`) and every panel —
Text, Character, Paragraph, Layer Style, Color, Gradients, Layers, Glossary —
is a QDockWidget around it: drag a panel's title out to float it as its own
window, resize it, drag it back to dock it or drop it on another panel to
tab the two together. The window's Window menu shows and hides each panel
and puts them all back where they started (`reset_panels`). Where they are
is saved on close and restored at start (`DOCK_STATE_KEY`); a saved state
that no longer fits (a panel added in a newer version) leaves the new panel
where the default layout puts it.

The editor's own QMainWindow is not used: its docks would show over the
home screen and the settings page, which share its central stack.
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

DOCK_STATE_KEY = "editor/dock_state"
# Bumped when the default arrangement changes, so an older saved layout is
# not restored over panels it does not know.
DOCK_STATE_VERSION = 1

Area = QtCore.Qt.DockWidgetArea


class DockMixin:
    def _make_dock(self, name: str, title: str, widget: QtWidgets.QWidget, scroll: bool = True):
        dock = QtWidgets.QDockWidget(title, self.editor_docks)
        dock.setObjectName(name)  # what saveState/restoreState key on
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setAllowedAreas(Area.LeftDockWidgetArea | Area.RightDockWidgetArea)
        if scroll:
            area = QtWidgets.QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(widget)
            area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            area.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            dock.setWidget(area)
        else:
            dock.setWidget(widget)
        dock.setMinimumWidth(300)
        self.panel_docks[name] = dock
        return dock

    def _build_dock_host(self, central: QtWidgets.QWidget, panels: list[tuple[str, str, QtWidgets.QWidget, bool]]):
        """The nested main window: `central` in the middle, one dock per panel."""
        host = QtWidgets.QMainWindow()
        host.setObjectName("toonDockHost")
        host.setWindowFlags(QtCore.Qt.WindowType.Widget)
        host.setDockOptions(
            QtWidgets.QMainWindow.DockOption.AnimatedDocks
            | QtWidgets.QMainWindow.DockOption.AllowNestedDocks
            | QtWidgets.QMainWindow.DockOption.AllowTabbedDocks
            | QtWidgets.QMainWindow.DockOption.GroupedDragging
        )
        host.setTabPosition(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas, QtWidgets.QTabWidget.TabPosition.North)
        host.setCentralWidget(central)
        self.editor_docks = host
        self.panel_docks: dict[str, QtWidgets.QDockWidget] = {}
        for name, title, widget, scroll in panels:
            self._make_dock(name, title, widget, scroll)
        self._arrange_default_docks()
        self._dock_first_show = _FirstShow(host, self._on_dock_host_first_show)
        return host

    def _on_dock_host_first_show(self) -> None:
        self._dock_host_shown = True
        # A restored layout keeps its own sizes; only the default is sized here.
        if not getattr(self, "_dock_state_restored", False):
            self._size_default_docks()

    # The default arrangement, Photoshop's right-hand column: the translation
    # and glossary on top, Character/Paragraph/Layer Style/Color/Gradients in
    # the middle, Layers at the bottom.
    DEFAULT_GROUPS = (
        ("dock_text", "dock_glossary"),
        ("dock_character", "dock_paragraph", "dock_layer_style", "dock_color", "dock_gradients"),
        ("dock_layers",),
    )

    def _arrange_default_docks(self) -> None:
        host = self.editor_docks
        groups = [[self.panel_docks[n] for n in group if n in self.panel_docks] for group in self.DEFAULT_GROUPS]
        groups = [g for g in groups if g]
        # Split the column first, then tab: Qt puts a dock split beside one
        # that is already tabbed into that tab group instead of below it.
        previous = None
        for group in groups:
            host.addDockWidget(Area.RightDockWidgetArea, group[0])
            if previous is not None:
                host.splitDockWidget(previous, group[0], QtCore.Qt.Orientation.Vertical)
            previous = group[0]
        for group in groups:
            for other in group[1:]:
                host.tabifyDockWidget(group[0], other)
            for dock in group:
                dock.show()
            group[0].raise_()
        listed = {n for group in self.DEFAULT_GROUPS for n in group}
        for name, dock in self.panel_docks.items():
            if name not in listed:
                host.addDockWidget(Area.RightDockWidgetArea, dock)
        self._default_firsts = [g[0] for g in groups]
        self._size_default_docks()

    def _size_default_docks(self) -> None:
        """The default group heights and column width. Qt sizes docks only once
        the host is laid out, so this runs again on the host's first show."""
        firsts = getattr(self, "_default_firsts", None) or []
        if not firsts:
            return
        heights = [self.DEFAULT_HEIGHTS.get(d.objectName(), 300) for d in firsts]
        self.editor_docks.resizeDocks(firsts, heights, QtCore.Qt.Orientation.Vertical)
        self.editor_docks.resizeDocks(firsts[:1], [340], QtCore.Qt.Orientation.Horizontal)

    # Starting heights of the three groups: the panel worked in most
    # (Character) gets the most room.
    DEFAULT_HEIGHTS = {"dock_text": 230, "dock_character": 420, "dock_layers": 260}

    def reset_panels(self) -> None:
        """Window › Reset Panels: every panel back where it started, shown."""
        # A floating panel docks back while it is still part of the layout;
        # after removeDockWidget Qt no longer knows where to put it.
        for dock in self.panel_docks.values():
            if dock.isFloating():
                dock.setFloating(False)
        for dock in self.panel_docks.values():
            self.editor_docks.removeDockWidget(dock)
        self._arrange_default_docks()
        QtCore.QTimer.singleShot(0, self._size_default_docks)

    def show_panel(self, name: str) -> None:
        dock = self.panel_docks.get(name)
        if dock is None:
            return
        dock.show()
        dock.raise_()

    # --- the Window menu -------------------------------------------------

    def build_window_menu(self, parent: QtWidgets.QWidget) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(parent)
        for dock in self.panel_docks.values():
            menu.addAction(dock.toggleViewAction())
        menu.addSeparator()
        menu.addAction(self.tr("Reset Panels"), self.reset_panels)
        return menu

    # --- saving the layout -----------------------------------------------

    def save_dock_state(self) -> None:
        from PySide6.QtCore import QSettings

        # A host never shown (the editor never opened this session) was never
        # laid out: its state holds no real sizes and would replace a good one.
        if not getattr(self, "_dock_host_shown", False):
            return
        settings = QSettings("ComicLabs", "ComicTranslate")
        settings.setValue(DOCK_STATE_KEY, self.editor_docks.saveState(DOCK_STATE_VERSION))

    def restore_dock_state(self) -> bool:
        from PySide6.QtCore import QSettings

        state = QSettings("ComicLabs", "ComicTranslate").value(DOCK_STATE_KEY)
        if not isinstance(state, (QtCore.QByteArray, bytes)) or not state:
            return False
        try:
            restored = bool(self.editor_docks.restoreState(QtCore.QByteArray(state), DOCK_STATE_VERSION))
        except Exception:  # noqa: BLE001 — a bad saved layout falls back to the default
            restored = False
        self._dock_state_restored = restored
        return restored


class _FirstShow(QtCore.QObject):
    """Calls back once, just after `widget` is first shown and laid out."""

    def __init__(self, widget: QtWidgets.QWidget, callback):
        super().__init__(widget)
        self._callback = callback
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Show:
            obj.removeEventFilter(self)
            QtCore.QTimer.singleShot(0, self._callback)
        return False
