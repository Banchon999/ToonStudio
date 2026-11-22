"""Panels as dock windows (Photoshop's): float, resize, tab, hide, reset, remembered."""

import pytest
from PySide6 import QtCore, QtWidgets


@pytest.fixture
def win(qapp):
    import controller

    window = controller.ComicTranslate()
    window.resize(1440, 900)
    window.show()
    window._center_stack.setCurrentWidget(window.main_content_widget)
    for _ in range(5):
        qapp.processEvents()
    yield window
    window._skip_close_prompt = True
    window.close()


def _tabbed(win, name):
    return {d.objectName() for d in win.editor_docks.tabifiedDockWidgets(win.panel_docks[name])}


def test_the_default_layout_is_three_groups_down_the_right(win):
    assert _tabbed(win, "dock_text") == {"dock_glossary"}
    assert {"dock_paragraph", "dock_layer_style"} <= _tabbed(win, "dock_character")
    assert _tabbed(win, "dock_layers") == set()
    text, character, layers = (win.panel_docks[n] for n in ("dock_text", "dock_character", "dock_layers"))
    assert text.geometry().bottom() < character.geometry().top() < layers.geometry().top()
    assert character.height() > text.height(), "the panel worked in most gets the most room"


def test_a_panel_floats_as_its_own_resizable_window_and_docks_back(win, qapp):
    dock = win.panel_docks["dock_character"]
    dock.setFloating(True)
    qapp.processEvents()
    assert dock.isFloating() and dock.isWindow()
    dock.resize(420, 640)
    qapp.processEvents()
    assert (dock.width(), dock.height()) == (420, 640)
    assert dock.isAncestorOf(win.font_dropdown), "its controls travel with it"
    dock.setFloating(False)
    qapp.processEvents()
    assert not dock.isFloating()


def test_the_window_menu_lists_every_panel_and_resets_them(win, qapp):
    menu = win.window_menu_button.menu()
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    for dock in win.panel_docks.values():
        assert dock.windowTitle() in labels
    win.panel_docks["dock_paragraph"].hide()
    win.panel_docks["dock_character"].setFloating(True)
    reset = next(a for a in menu.actions() if a.text() == "Reset Panels")
    reset.trigger()
    qapp.processEvents()
    assert not win.panel_docks["dock_character"].isFloating()
    assert {"dock_paragraph", "dock_layer_style"} <= _tabbed(win, "dock_character")


def test_the_layout_is_remembered_for_the_next_start(qapp):
    import controller

    first = controller.ComicTranslate()
    first.show()
    first.panel_docks["dock_glossary"].setFloating(True)
    first.panel_docks["dock_paragraph"].hide()
    qapp.processEvents()
    first._skip_close_prompt = True
    first.close()  # saves the layout
    second = controller.ComicTranslate()
    try:
        assert second.panel_docks["dock_glossary"].isFloating()
        assert second.panel_docks["dock_paragraph"].isHidden()
    finally:
        second.reset_panels()
        second.save_dock_state()
        second._skip_close_prompt = True
        second.close()
