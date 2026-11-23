"""Panels as dock windows (Photoshop's): float, resize, tab, hide, reset, remembered."""

import pytest
from PySide6 import QtCore, QtWidgets


@pytest.fixture
def win(qapp):
    import controller
    from app.ui.main_window.docks import DOCK_STATE_KEY

    # Start from the default layout, not whatever an earlier test's window
    # left saved (a panel it closed stays closed, as it should for a user).
    QtCore.QSettings("ComicLabs", "ComicTranslate").remove(DOCK_STATE_KEY)
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
    first._center_stack.setCurrentWidget(first.main_content_widget)
    for _ in range(3):
        qapp.processEvents()
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
        from app.ui.main_window.docks import DOCK_STATE_KEY

        second._skip_close_prompt = True
        second.close()
        QtCore.QSettings("ComicLabs", "ComicTranslate").remove(DOCK_STATE_KEY)


def test_a_window_whose_editor_was_never_shown_keeps_the_saved_layout(qapp):
    """Closing from the home screen must not replace a real layout with one
    that was never laid out (no sizes, every panel where Qt first put it)."""
    import controller
    from app.ui.main_window.docks import DOCK_STATE_KEY

    settings = QtCore.QSettings("ComicLabs", "ComicTranslate")
    settings.setValue(DOCK_STATE_KEY, QtCore.QByteArray(b"saved-by-a-real-session"))
    window = controller.ComicTranslate()
    try:
        window._skip_close_prompt = True
        window.close()
        assert bytes(settings.value(DOCK_STATE_KEY)) == b"saved-by-a-real-session"
    finally:
        settings.remove(DOCK_STATE_KEY)


def test_floating_panels_show_on_the_editor_page_only(win, qapp):
    """A floating panel is its own window: it must not sit over the settings
    or the home screen. One the user closed stays closed on coming back."""
    color, gradients = win.panel_docks["dock_color"], win.panel_docks["dock_gradients"]
    for dock in (color, gradients):
        dock.setFloating(True)
        dock.show()
    qapp.processEvents()
    gradients.close()
    qapp.processEvents()
    win.show_settings_page()
    qapp.processEvents()
    assert not color.isVisible()
    win.show_main_page()
    qapp.processEvents()
    assert color.isVisible() and color.isFloating()
    assert not gradients.isVisible(), "closed by the user, not by the page"
    win.show_home_screen()
    qapp.processEvents()
    assert not color.isVisible()


def test_a_layout_saved_from_another_page_keeps_its_floating_panels(qapp):
    import controller
    from app.ui.main_window.docks import DOCK_STATE_KEY

    settings = QtCore.QSettings("ComicLabs", "ComicTranslate")
    settings.remove(DOCK_STATE_KEY)
    first = controller.ComicTranslate()
    first.show()
    first._center_stack.setCurrentWidget(first.main_content_widget)
    for _ in range(3):
        qapp.processEvents()
    first.panel_docks["dock_color"].setFloating(True)
    first.panel_docks["dock_color"].show()
    first.show_settings_page()  # quit from the settings page
    qapp.processEvents()
    first._skip_close_prompt = True
    first.close()
    second = controller.ComicTranslate()
    try:
        second.show()
        qapp.processEvents()
        color = second.panel_docks["dock_color"]
        assert color.isFloating()
        assert not color.isVisible(), "not over the home screen the app opens on"
        second._center_stack.setCurrentWidget(second.main_content_widget)
        qapp.processEvents()
        assert color.isVisible(), "shown once the editor (and the window) is"
    finally:
        second._skip_close_prompt = True
        second.close()
        settings.remove(DOCK_STATE_KEY)
