"""The Color and Gradients panels (Photoshop's), acting on the selected text layers only."""

import json

import numpy as np
import pytest
from PySide6 import QtGui
from PySide6.QtCore import QPointF

from core import gradient_presets as gp


class TestPresets:
    def test_every_builtin_gradient_is_two_real_colours(self):
        names = [name for name, _ in gp.BUILTIN]
        assert names[:6] == ["Basics", "Blues", "Purples", "Pinks", "Reds", "Oranges"]
        for _folder, gradients in gp.BUILTIN:
            assert gradients
            assert len({g.name for g in gradients}) == len(gradients)
            for g in gradients:
                assert gp.valid_hex(g.start) and gp.valid_hex(g.end) and g.start != g.end

    def test_my_gradients_round_trip_and_skip_duplicates(self, tmp_path):
        path = str(tmp_path / "sub" / "gradients.json")
        mine = gp.add_custom([], "#FF0000", "#0000ff", "Red Blue")
        mine = gp.add_custom(mine, "#ff0000", "#0000FF")  # the same pair
        assert [(g.name, g.start, g.end) for g in mine] == [("Red Blue", "#ff0000", "#0000ff")]
        mine = gp.add_custom(mine, "#000000", "#ffffff")
        gp.save_custom(path, mine)
        assert gp.load_custom(path) == mine
        assert gp.remove_custom(mine, 0) == mine[1:]
        with pytest.raises(ValueError):
            gp.add_custom(mine, "red", "#ffffff")

    def test_a_damaged_file_is_no_gradients(self, tmp_path):
        bad = tmp_path / "gradients.json"
        bad.write_text("{not json")
        assert gp.load_custom(str(bad)) == []
        bad.write_text(json.dumps([{"start": "#zzzzzz", "end": "#000000"}, "x", {"start": "#111111", "end": "#222222"}]))
        assert [(g.start, g.end) for g in gp.load_custom(str(bad))] == [("#111111", "#222222")]


@pytest.fixture
def win(qapp):
    import controller

    window = controller.ComicTranslate()
    window.image_viewer.display_image_array(np.full((400, 600, 3), 230, dtype=np.uint8))
    stack = QtGui.QUndoStack()
    window.undo_group.addStack(stack)
    window.undo_group.setActiveStack(stack)
    window._stack = stack
    window.type_text_button.setChecked(True)
    window.toggle_type_text_tool()
    items = []
    for i, text in enumerate(("ONE", "TWO", "THREE")):
        window.image_viewer.add_text_requested.emit(QPointF(40, 40 + i * 100))
        item = window.image_viewer.text_items[-1]
        item.textCursor().insertText(text)
        window.text_ctrl._commit_pending_text_command()
        cursor = item.textCursor()
        cursor.clearSelection()
        item.setTextCursor(cursor)
        items.append(item)
    window.set_tool(None)
    window._items = items
    yield window
    window._skip_close_prompt = True
    window.close()


def _select(win, *chosen):
    """Select layers as the Layers panel does: on the canvas's scene."""
    for item in win.image_viewer.text_items:
        item.setSelected(item in chosen)
        item.selected = item in chosen
    win.curr_tblock_item = chosen[0] if chosen else None


def _colours(item) -> set[str]:
    """The colours the item is drawn in (strong red, green, blue or black ink)."""
    import numpy as np
    from PySide6 import QtWidgets

    rect = item.boundingRect()
    image = QtGui.QImage(int(rect.width()) + 2, int(rect.height()) + 2, QtGui.QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QtGui.QPainter(image)
    item.paint(painter, QtWidgets.QStyleOptionGraphicsItem(), None)
    painter.end()
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
    ink = pixels[pixels[..., 3] > 200][:, 2::-1].astype(int)  # BGRA → RGB
    found = set()
    for name, rgb in (("#ff0000", (255, 0, 0)), ("#00ff00", (0, 255, 0)), ("#0000ff", (0, 0, 255)), ("#000000", (0, 0, 0))):
        if (np.abs(ink - rgb).max(axis=1) < 40).sum() > 5:
            found.add(name)
    return found


def test_both_panels_are_dock_windows_beside_character(win):
    tabbed = {d.objectName() for d in win.editor_docks.tabifiedDockWidgets(win.panel_docks["dock_character"])}
    assert {"dock_color", "dock_gradients"} <= tabbed
    assert win.panel_docks["dock_color"].isAncestorOf(win.color_panel)
    assert win.panel_docks["dock_gradients"].isAncestorOf(win.gradients_panel)


def test_dragging_a_colour_previews_and_settles_as_one_undo_step(win):
    one, two, three = win._items
    _select(win, one, two)
    before = win._stack.count()
    panel = win.color_panel
    panel.hue_strip.moved.emit(0.0)  # red hue
    panel.square._pick(QPointF(panel.square.width() - 1, 0))  # full saturation and brightness
    assert _colours(one) == {"#ff0000"} and _colours(two) == {"#ff0000"}, "seen while dragging"
    assert win._stack.count() == before, "nothing is an undo step until the release"
    panel.square.released.emit()
    assert win._stack.count() == before + 1, "one step for both layers"
    assert "#ff0000" not in _colours(three), "an unselected layer is left alone"
    assert QtGui.QColor(one.text_color).name() == "#ff0000"
    assert win.block_font_color_button.property("selected_color") == "#ff0000"
    win._stack.undo()
    assert "#ff0000" not in _colours(one) | _colours(two)


def test_a_typed_colour_on_the_stroke_target_outlines_the_selection(win):
    one, two, _three = win._items
    _select(win, two)
    panel = win.color_panel
    panel.set_target("stroke")
    panel.hex_edit.setText("00ff00")
    panel.hex_edit.editingFinished.emit()
    assert two.outline and QtGui.QColor(two.outline_color).name() == "#00ff00"
    assert not one.outline or QtGui.QColor(one.outline_color).name() != "#00ff00"
    assert "#00ff00" in panel.recent()


def test_the_panel_shows_the_selected_layers_colours(win):
    one = win._items[0]
    one.set_color(QtGui.QColor("#123456"))
    one.set_outline(QtGui.QColor("#abcdef"), 2.0)
    win.text_ctrl.set_values_for_blk_item(one)
    panel = win.color_panel
    assert panel.color("fill").name() == "#123456"
    assert panel.color("stroke").name() == "#abcdef"
    assert panel.hex_edit.text() == "#123456"


def test_a_gradient_preset_goes_on_the_selected_layers_only(win):
    one, two, three = win._items
    one.gradient_angle = 45.0
    _select(win, one, two)
    before = win._stack.count()
    win.gradients_panel.choose(gp.Gradient("t", "#ff0000", "#0000ff"))
    for item in (one, two):
        assert item.gradient_enabled
        assert QtGui.QColor(item.text_color).name() == "#ff0000"
        assert QtGui.QColor(item.gradient_color).name() == "#0000ff"
    assert one.gradient_angle == 45.0, "each keeps its own angle"
    assert not three.gradient_enabled
    assert win._stack.count() == before + 1
    assert win.gradient_checkbox.isChecked()
    win._stack.undo()
    assert not one.gradient_enabled and not two.gradient_enabled


def test_reverse_swaps_the_stops(win):
    one = win._items[0]
    _select(win, one)
    win.gradients_panel.reverse_button.setChecked(True)
    win.gradients_panel.choose(gp.Gradient("t", "#ff0000", "#0000ff"))
    assert QtGui.QColor(one.text_color).name() == "#0000ff"
    assert QtGui.QColor(one.gradient_color).name() == "#ff0000"


def test_a_tile_click_applies_its_gradient(win):
    one = win._items[0]
    _select(win, one)
    tile = win.gradients_panel.tiles("Blues")[0]
    tile.click()
    assert QtGui.QColor(one.gradient_color).name() == tile.gradient.end


def test_saving_the_selected_gradient_puts_it_in_my_gradients(win):
    from app.ui.gradients_panel import custom_path

    one = win._items[0]
    _select(win, one)
    one.set_color(QtGui.QColor("#112233"))
    one.set_gradient(True, QtGui.QColor("#445566"))
    win.gradients_panel.add_button.click()
    mine = win.gradients_panel.tiles(gp.CUSTOM_FOLDER)
    assert [(t.gradient.start, t.gradient.end) for t in mine][-1] == ("#112233", "#445566")
    assert (gp.load_custom(custom_path())[-1].start, gp.load_custom(custom_path())[-1].end) == ("#112233", "#445566")
    win.gradients_panel.remove_custom(len(mine) - 1)
    assert all(t.gradient.start != "#112233" for t in win.gradients_panel.tiles(gp.CUSTOM_FOLDER))
