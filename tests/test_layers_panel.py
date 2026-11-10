"""Slice 5: the Layers panel drives LayerController and mirrors the scene."""

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QUndoStack

from core.layers import LayerGroup
from app.ui.layers_panel import COL_LOCK, COL_NAME, COL_VIS, ROLE_GROUP, ROLE_OBJECT


def _text_props(**kw):
    from app.ui.canvas.text.text_item_properties import TextItemProperties

    base = dict(text="<p>Hello there</p>", position=(10, 10), width=120,
                text_color=QColor("#101010"), outline_color=QColor("#ffffff"))
    base.update(kw)
    return TextItemProperties(**base)


@pytest.fixture
def ct(qapp):
    import controller as controller_mod

    win = controller_mod.ComicTranslate()
    win.image_viewer.display_image_array(np.full((300, 400, 3), 220, np.uint8))
    stack = QUndoStack(win.undo_group)
    win.undo_group.addStack(stack)
    win.undo_group.setActiveStack(stack)
    win.layers_panel.setVisible(True)
    yield win
    win._skip_close_prompt = True
    win.close()


def _group_row(panel, group):
    tree = panel.tree
    for i in range(tree.topLevelItemCount()):
        row = tree.topLevelItem(i)
        if row.data(COL_NAME, ROLE_GROUP) == group.value:
            return row
    raise AssertionError(group)


def _object_row(panel, oid):
    tree = panel.tree
    for i in range(tree.topLevelItemCount()):
        g = tree.topLevelItem(i)
        for j in range(g.childCount()):
            if g.child(j).data(COL_NAME, ROLE_OBJECT) == oid:
                return g.child(j)
    raise AssertionError(oid)


def test_rows_mirror_the_scene(ct):
    text = ct.image_viewer.add_text_item(_text_props())
    rect = ct.image_viewer.add_rectangle(QRectF(0, 0, 30, 30), QPointF(200, 200))
    ct.layers_panel.rebuild()

    order = [ct.layers_panel.tree.topLevelItem(i).data(COL_NAME, ROLE_GROUP)
             for i in range(ct.layers_panel.tree.topLevelItemCount())]
    assert order == ["text", "boxes", "strokes", "patches", "raw"]  # topmost first
    assert _object_row(ct.layers_panel, text.object_id).text(COL_NAME) == "Hello there"
    assert _object_row(ct.layers_panel, rect.object_id).text(COL_NAME) == "Box 1"
    assert _group_row(ct.layers_panel, LayerGroup.TEXT).childCount() == 1


def test_eye_on_an_object_hides_it_undoably(ct):
    text = ct.image_viewer.add_text_item(_text_props())
    ct.layers_panel.rebuild()
    ct.layers_panel._on_item_clicked(_object_row(ct.layers_panel, text.object_id), COL_VIS)
    assert not text.isVisible()
    ct.undo_group.undo()
    assert text.isVisible()


def test_group_eye_and_lock_apply_document_wide(ct):
    text = ct.image_viewer.add_text_item(_text_props())
    ct.layers_panel.rebuild()
    ct.layers_panel._on_item_clicked(_group_row(ct.layers_panel, LayerGroup.TEXT), COL_VIS)
    assert not text.isVisible()
    assert ct.document_layers.group(LayerGroup.TEXT).visible is False
    ct.layers_panel._on_item_clicked(_group_row(ct.layers_panel, LayerGroup.TEXT), COL_LOCK)
    assert ct.document_layers.group(LayerGroup.TEXT).locked is True


def test_rename_through_the_tree(ct):
    text = ct.image_viewer.add_text_item(_text_props())
    ct.layers_panel.rebuild()
    _object_row(ct.layers_panel, text.object_id).setText(COL_NAME, "Title SFX")
    assert ct.layer_ctrl.object_props(text.object_id).name == "Title SFX"
    ct.layers_panel.rebuild()
    assert _object_row(ct.layers_panel, text.object_id).text(COL_NAME) == "Title SFX"


def test_opacity_slider_sets_selected_objects(ct):
    a = ct.image_viewer.add_rectangle(QRectF(0, 0, 30, 30), QPointF(10, 10))
    b = ct.image_viewer.add_rectangle(QRectF(0, 0, 30, 30), QPointF(100, 100))
    ct.layers_panel.rebuild()
    _object_row(ct.layers_panel, a.object_id).setSelected(True)
    _object_row(ct.layers_panel, b.object_id).setSelected(True)
    ct.layers_panel._on_opacity_committed(40)
    assert a.opacity() == pytest.approx(0.4) and b.opacity() == pytest.approx(0.4)


def test_move_up_reorders_within_the_group(ct):
    a = ct.image_viewer.add_rectangle(QRectF(0, 0, 30, 30), QPointF(10, 10))
    b = ct.image_viewer.add_rectangle(QRectF(0, 0, 30, 30), QPointF(100, 100))
    ct.layers_panel.rebuild()
    group = _group_row(ct.layers_panel, LayerGroup.BOXES)
    top_first = [group.child(i).data(COL_NAME, ROLE_OBJECT) for i in range(group.childCount())]
    bottom_id = top_first[-1]
    ct.layers_panel.tree.clearSelection()
    _object_row(ct.layers_panel, bottom_id).setSelected(True)
    ct.layers_panel._move_selected(+1)
    ct.layers_panel.rebuild()
    group = _group_row(ct.layers_panel, LayerGroup.BOXES)
    assert group.child(0).data(COL_NAME, ROLE_OBJECT) == bottom_id
    items = {a.object_id: a, b.object_id: b}
    assert items[bottom_id].zValue() > items[top_first[0]].zValue()


def test_selecting_a_text_row_selects_it_on_canvas(ct):
    text = ct.image_viewer.add_text_item(_text_props())
    ct.layers_panel.rebuild()
    _object_row(ct.layers_panel, text.object_id).setSelected(True)
    assert text.selected


def test_panel_follows_undo(ct):
    """A change made elsewhere (here: undoing a hide) shows up in the panel."""
    text = ct.image_viewer.add_text_item(_text_props())
    ct.layer_ctrl.set_object_props([text.object_id], visible=False)
    ct.layers_panel.rebuild()
    hidden_icon = _object_row(ct.layers_panel, text.object_id).icon(COL_VIS).cacheKey()
    ct.undo_group.undo()
    ct.layers_panel.rebuild()
    assert _object_row(ct.layers_panel, text.object_id).icon(COL_VIS).cacheKey() != hidden_icon


def test_a_stroke_without_an_id_still_gets_a_row(ct):
    from PySide6.QtGui import QPainterPath, QPen

    path = QPainterPath()
    path.moveTo(0, 0)
    path.lineTo(50, 50)
    stroke = ct.image_viewer._scene.addPath(path, QPen(QColor("#80ff0000")))
    ct.layers_panel.rebuild()
    assert _group_row(ct.layers_panel, LayerGroup.STROKES).childCount() == 1
    from app.ui.canvas.scene_registry import object_id_of
    assert object_id_of(stroke)  # stamped, so edits can address it


# --- showing one layer alone (Alt+click on the eye, as PhotoCraft and
# Photoshop do) and the row's right-click menu ---------------------------------


def _alt_click(monkeypatch, panel, row):
    from PySide6 import QtWidgets
    from PySide6.QtCore import Qt

    monkeypatch.setattr(QtWidgets.QApplication, "keyboardModifiers",
                        staticmethod(lambda: Qt.KeyboardModifier.AltModifier))
    panel._on_item_clicked(row, COL_VIS)


def test_alt_click_on_an_eye_shows_that_layer_alone_and_again_shows_all(ct, monkeypatch):
    a = ct.image_viewer.add_text_item(_text_props(text="<p>one</p>"))
    b = ct.image_viewer.add_text_item(_text_props(text="<p>two</p>", position=(10, 80)))
    c = ct.image_viewer.add_text_item(_text_props(text="<p>three</p>", position=(10, 150)))
    box = ct.image_viewer.add_rectangle(QRectF(0, 0, 30, 30), QPointF(200, 200))
    panel = ct.layers_panel
    panel.rebuild()

    _alt_click(monkeypatch, panel, _object_row(panel, b.object_id))
    assert [a.isVisible(), b.isVisible(), c.isVisible()] == [False, True, False]
    assert box.isVisible()                       # other groups are not touched

    panel.rebuild()
    _alt_click(monkeypatch, panel, _object_row(panel, b.object_id))
    assert all(item.isVisible() for item in (a, b, c))

    ct.undo_group.undo()                         # each is one undo step
    assert [a.isVisible(), b.isVisible(), c.isVisible()] == [False, True, False]
    ct.undo_group.undo()
    assert all(item.isVisible() for item in (a, b, c))


def test_alt_click_on_a_hidden_layer_shows_it_alone(ct, monkeypatch):
    a = ct.image_viewer.add_text_item(_text_props(text="<p>one</p>"))
    b = ct.image_viewer.add_text_item(_text_props(text="<p>two</p>", position=(10, 80)))
    ct.layer_ctrl.set_object_props([b.object_id], visible=False)
    panel = ct.layers_panel
    panel.rebuild()
    _alt_click(monkeypatch, panel, _object_row(panel, b.object_id))
    assert not a.isVisible() and b.isVisible()


def test_a_lone_layer_has_nothing_to_hide(ct):
    a = ct.image_viewer.add_text_item(_text_props())
    assert ct.layer_ctrl.solo(a.object_id) is False
    assert a.isVisible()


def test_alt_click_on_a_group_eye_shows_that_group_over_the_page(ct, monkeypatch):
    text = ct.image_viewer.add_text_item(_text_props())
    box = ct.image_viewer.add_rectangle(QRectF(0, 0, 30, 30), QPointF(200, 200))
    panel = ct.layers_panel
    panel.rebuild()

    _alt_click(monkeypatch, panel, _group_row(panel, LayerGroup.TEXT))
    assert text.isVisible() and not box.isVisible()
    assert ct.image_viewer.photo.isVisible()     # the page stays under it

    panel.rebuild()
    _alt_click(monkeypatch, panel, _group_row(panel, LayerGroup.TEXT))
    assert text.isVisible() and box.isVisible()


def test_the_row_menu_offers_what_the_row_can_do(ct):
    a = ct.image_viewer.add_text_item(_text_props(text="<p>one</p>"))
    b = ct.image_viewer.add_text_item(_text_props(text="<p>two</p>", position=(10, 80)))
    panel = ct.layers_panel
    panel.rebuild()

    def pick(row, label):
        panel.tree.setCurrentItem(row)
        menu = panel._build_context_menu(row)
        actions = {act.text(): act for act in menu.actions() if not act.isSeparator()}
        if label:
            actions[label].trigger()
        return list(actions)

    labels = pick(_object_row(panel, a.object_id), "Show Only This Layer")
    assert labels == ["Hide", "Show Only This Layer", "Lock", "Rename", "Delete"]
    assert a.isVisible() and not b.isVisible()

    panel.rebuild()
    pick(_object_row(panel, a.object_id), "Lock")
    assert ct.layer_ctrl.object_props(a.object_id).locked

    panel.rebuild()
    assert pick(_group_row(panel, LayerGroup.TEXT), None) == [
        "Hide Group", "Show Only This Group", "Lock Group"]
    assert pick(_group_row(panel, LayerGroup.RAW), None) == ["Hide Group"]
