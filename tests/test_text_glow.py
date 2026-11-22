"""Outer glow on text, and the direction dial for the shadow and gradient."""

import math

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor

from core.text_glow import box_radius, glow_alpha, glow_reach, glow_rgba


class TestGlowMaths:
    def test_the_glow_is_solid_at_the_letters_and_gone_past_its_reach(self):
        silhouette = np.zeros((80, 80), np.uint8)
        silhouette[30:50, 30:50] = 255
        alpha = glow_alpha(silhouette, 12)
        assert alpha[40, 40] == 1.0
        assert alpha[40, 51] > 0.75, "strong right against the edge"
        reach = int(glow_reach(12))
        assert alpha[40, 50 + reach + 1] == 0.0
        assert 0.0 < alpha[40, 55] < alpha[40, 52], "it fades outward"

    def test_no_size_no_glow(self):
        assert not glow_alpha(np.full((5, 5), 255, np.uint8), 0).any()
        assert glow_reach(0) == 0.0 and box_radius(1) == 1

    def test_the_colour_is_premultiplied_by_strength(self):
        silhouette = np.zeros((20, 20), np.uint8)
        silhouette[8:12, 8:12] = 255
        out = glow_rgba(silhouette, 4, (255, 0, 0, 128))
        centre = out[10, 10]
        assert centre[3] == 128 and centre[0] == 128 and centre[1] == 0


def _item(qapp, **glow):
    from app.ui.canvas.text_item import TextBlockItem

    item = TextBlockItem(text="GLOW", font_family="DejaVu Sans", font_size=40)
    item.set_font("DejaVu Sans", 40)
    item.set_color(QColor("#ffffff"))
    if glow:
        item.set_glow(True, glow.get("color", QColor(255, 0, 255, 255)), glow.get("size", 10))
    return item


def _render(item, rect):
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(item)
    image = QtGui.QImage(int(rect.width()), int(rect.height()), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QColor("#000000"))
    painter = QtGui.QPainter(image)
    scene.render(painter, QtCore.QRectF(image.rect()), rect)
    painter.end()
    scene.removeItem(item)
    return image


def _magenta(image):
    return sum(
        1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
        if (c := image.pixelColor(x, y)).red() > 60 and c.blue() > 60 and c.green() < 40
    )


@pytest.mark.parametrize("engine", ["qt", "skia"])
def test_a_glowing_item_draws_a_coloured_halo_beyond_its_letters(qapp, engine):
    from core import text_engine

    if engine not in text_engine.available_engines():
        pytest.skip("skia not installed")
    previous = text_engine.engine()
    text_engine.set_engine(engine)
    try:
        plain = _item(qapp)
        glowing = _item(qapp, size=10)
        assert glowing.boundingRect().width() > plain.boundingRect().width() + 15
        assert glowing.text_rect() == plain.text_rect(), "the box itself does not move"
        rect = glowing.boundingRect().adjusted(-4, -4, 4, 4)
        assert _magenta(_render(plain, rect)) == 0
        assert _magenta(_render(glowing, rect)) > 40
    finally:
        text_engine.set_engine(previous)


def test_the_glow_is_saved_and_restored(qapp):
    from app.ui.canvas.text.text_item_properties import TextItemProperties

    item = _item(qapp, color=QColor(0, 200, 255, 150), size=14)
    data = TextItemProperties.from_text_item(item).to_dict()
    assert data["glow_enabled"] and data["glow_size"] == 14
    props = TextItemProperties.from_dict(data)
    assert props.glow_enabled and props.glow_color.alpha() == 150
    assert "glow_enabled" not in TextItemProperties.from_text_item(_item(qapp)).to_dict(), "no glow, no keys"


def test_a_style_preset_carries_the_glow(qapp):
    from app.ui.canvas.text.presets import apply_preset_to_item, preset_from_item
    from modules.utils.text_presets import LOOK_FIELDS

    preset = preset_from_item(_item(qapp, size=12), "Neon")
    other = _item(qapp)
    apply_preset_to_item(other, preset, LOOK_FIELDS)
    assert other.glow_enabled and other.glow_size == 12


class TestDialMaths:
    def test_offset_and_angle_round_trip(self):
        from app.ui.angle_dial import angle_at, offset_for, polar_of, snapped

        assert angle_at(1, 0) == 0 and angle_at(0, 1) == 90 and angle_at(-1, 0) == 180
        dx, dy = offset_for(45, math.hypot(4, 4))
        assert (round(dx, 3), round(dy, 3)) == (4.0, 4.0)
        angle, distance = polar_of(-3, 0)
        assert angle == 180 and distance == 3
        assert polar_of(0, 0) == (45.0, 0.0)
        assert snapped(52) == 45 and snapped(359) == 0


def test_dragging_the_dial_points_it_and_commits_once_on_release(qapp):
    from PySide6.QtTest import QTest

    from app.ui.angle_dial import AngleDial

    dial = AngleDial(0)
    moved, committed = [], []
    dial.angle_changed.connect(moved.append)
    dial.angle_committed.connect(committed.append)
    centre = QtCore.QPoint(20, 20)
    QTest.mousePress(dial, QtCore.Qt.MouseButton.LeftButton, pos=centre + QtCore.QPoint(0, 15))
    QTest.mouseRelease(dial, QtCore.Qt.MouseButton.LeftButton, pos=centre + QtCore.QPoint(0, 15))
    assert round(dial.angle()) == 90 and len(committed) == 1 and round(committed[0]) == 90


@pytest.fixture
def window(qapp):
    import controller

    win = controller.ComicTranslate()
    win.image_viewer.display_image_array(np.full((300, 600, 3), 230, dtype=np.uint8))
    stack = QtGui.QUndoStack()
    win.undo_group.addStack(stack)
    win.undo_group.setActiveStack(stack)
    win._test_stack = stack
    win.type_text_button.setChecked(True)
    win.toggle_type_text_tool()
    win.image_viewer.add_text_requested.emit(QPointF(40, 60))
    item = win.image_viewer.text_items[-1]
    item.textCursor().insertText("HELLO")
    win.text_ctrl._commit_pending_text_command()
    win.text_ctrl.on_text_item_selected(item)
    win._item = item
    yield win
    win._skip_close_prompt = True
    win.close()


def test_the_panel_turns_glow_on_in_one_undo_step(window):
    item = window._item
    window.glow_size_dropdown.setCurrentText("16")
    window.glow_checkbox.setChecked(True)
    assert item.glow_enabled and item.glow_size == 16
    window._test_stack.undo()
    assert not item.glow_enabled


def test_the_shadow_dial_and_distance_set_the_offset(window):
    item = window._item
    window.shadow_checkbox.setChecked(True)
    window.shadow_angle_dial.set_angle(180)
    window.shadow_distance_dropdown.setCurrentText("6")
    assert item.shadow_enabled
    assert tuple(round(v, 2) for v in item.shadow_offset) == (-6.0, 0.0)
    window.text_ctrl.set_values_for_blk_item(item)
    assert round(window.shadow_angle_dial.angle()) == 180
    assert window.shadow_distance_dropdown.currentText() == "6"


def test_the_gradient_dial_and_angle_box_follow_each_other(window):
    item = window._item
    window.gradient_checkbox.setChecked(True)
    window.text_ctrl.on_gradient_dial_committed(135.0)
    assert window.gradient_angle_dropdown.currentText() == "135"
    assert item.gradient_angle == 135
    window.gradient_angle_dropdown.setCurrentText("45")
    assert round(window.gradient_angle_dial.angle()) == 45


def test_an_exported_text_item_carries_its_glow(qapp):
    """The flattened export and a PSD's type-layer raster both come from here."""
    from app.ui.canvas.save_renderer import render_text_item_rgba
    from app.ui.canvas.text.text_item_properties import TextItemProperties

    state = TextItemProperties.from_text_item(_item(qapp, color=QColor(255, 0, 255, 255), size=10)).to_dict()
    state["position"] = (40, 40)
    top, left, rgba = render_text_item_rgba(state, 400, 200)
    magenta = (rgba[..., 0] > 120) & (rgba[..., 2] > 120) & (rgba[..., 1] < 60) & (rgba[..., 3] > 40)
    assert magenta.sum() > 100


def test_the_dial_draws_its_needle_where_it_points(qapp):
    from app.ui.angle_dial import AngleDial

    dial = AngleDial(0)
    image = dial.grab().toImage()  # paints it; a paint error raised here once
    assert not image.isNull()
    dial.set_angle(90)
    below = dial.grab().toImage().pixelColor(20, 32)
    right = dial.grab().toImage().pixelColor(32, 20)
    assert below != right, "the needle moved from the right to the bottom"
