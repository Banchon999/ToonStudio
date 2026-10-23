"""Undoable edits to objects' own layer props (hide, lock, opacity, rename, order).

Each change is recorded as (object_id, old props, new props). Applying it sets
the props on the live scene item when the object is on screen, and on its
stored state otherwise — a webtoon page scrolled out of view, or a page the
user has since left — so undoing later still lands. Patches are also kept in
``image_patches``, their persistent store, which is what the project saves.
"""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from app.ui.canvas.scene_registry import find_by_id, set_item_layer
from core.layers import layer_dict


def _update_state_lists(main, object_id: str, layer: dict | None) -> bool:
    """Write the props into every stored copy of the object. A page-spanning
    webtoon object is stored once per page it touches, all with one id."""
    found = False

    def _put(entry: dict) -> None:
        nonlocal found
        found = True
        if layer:
            entry["layer"] = dict(layer)
        else:
            entry.pop("layer", None)

    for plist in getattr(main, "image_patches", {}).values():
        for entry in plist:
            if entry.get("object_id") == object_id:
                _put(entry)
    for plist in getattr(main, "in_memory_patches", {}).values():
        for entry in plist:
            if entry.get("object_id") == object_id:
                _put(entry)

    states = getattr(main, "image_states", {})
    for state in states.values():
        if not isinstance(state, dict):
            continue
        viewer_state = state.get("viewer_state") or {}
        for key in ("rectangles", "text_items_state"):
            for entry in viewer_state.get(key) or []:
                if isinstance(entry, dict) and entry.get("object_id") == object_id:
                    _put(entry)
        for entry in state.get("brush_strokes") or []:
            if isinstance(entry, dict) and entry.get("object_id") == object_id:
                _put(entry)
    return found


def apply_object_layer(main, object_id: str, layer: dict | None) -> None:
    viewer = main.image_viewer
    item = find_by_id(viewer._scene, object_id, viewer=viewer)
    if item is not None:
        set_item_layer(item, layer)
    # Stored copies too: patches persist through image_patches, and an object
    # on an unloaded page exists only there.
    _update_state_lists(main, object_id, layer)


class SetLayerPropsCommand(QUndoCommand):
    def __init__(self, main, changes: list[tuple[str, dict | None, dict | None]], text: str = "Layer"):
        super().__init__(text)
        self.main = main
        self.changes = [(oid, layer_dict(old), layer_dict(new)) for oid, old, new in changes]

    def _apply(self, use_new: bool) -> None:
        for oid, old, new in self.changes:
            apply_object_layer(self.main, oid, new if use_new else old)
        self.main.image_viewer.refresh_layers()

    def redo(self):
        self._apply(True)

    def undo(self):
        self._apply(False)


# --- deleting a layer ----------------------------------------------------------
#
# The Layers panel's Delete takes one object off its page, whatever its kind.
# Each is the inverse of the command that put such an object there, so undo
# brings back the same object (same id, same layer props), and a patch is
# removed from ``image_patches`` too — that list is what a webtoon page reloads
# from and what the project saves.


class RemovePatchCommand(QUndoCommand):
    """One inpaint patch off the page: PatchInsertCommand run backwards."""

    def __init__(self, main, entry: dict, file_path: str, item=None):
        super().__init__("Delete patch")
        from app.ui.commands.inpaint import PatchInsertCommand

        insert = PatchInsertCommand.__new__(PatchInsertCommand)
        QUndoCommand.__init__(insert, "Insert patches")
        insert.ct = main
        insert.viewer = main.image_viewer
        insert.scene = insert.viewer._scene
        insert.file_path = file_path
        insert.display = True
        prop = dict(entry)
        prop.pop("image", None)
        if item is not None and getattr(insert.viewer, "webtoon_mode", False):
            # Where it is drawn now; a stored scene position can be stale.
            prop["scene_pos"] = [item.pos().x(), item.pos().y()]
        insert.properties_list = [prop]
        self._insert = insert

    def redo(self):
        self._insert.undo()
        self._insert.ct.image_viewer.refresh_layers()

    def undo(self):
        self._insert.redo()
        self._insert.ct.image_viewer.refresh_layers()


class RemoveStrokeCommand(QUndoCommand):
    """One brush or segmentation stroke off the page."""

    def __init__(self, viewer, item):
        super().__init__("Delete stroke")
        from app.ui.commands.base import PathCommandBase

        self._base = PathCommandBase
        self.viewer = viewer
        self.scene = viewer._scene
        self.properties = PathCommandBase.save_path_properties(item)

    def redo(self):
        item = self._base.find_matching_item(self.scene, self.properties)
        if item is not None:
            self.scene.removeItem(item)
            self.scene.update()

    def undo(self):
        if self._base.find_matching_item(self.scene, self.properties) is None:
            self.scene.addItem(self._base.create_path_item(self.properties))
            self.viewer.refresh_layers()


class RemoveTextItemCommand(QUndoCommand):
    """One rendered text item off the page. Its block (the detected box, the
    OCR text and the translation) stays, so Render can draw it again."""

    def __init__(self, main, item):
        super().__init__("Delete text")
        from app.ui.commands.base import RectCommandBase

        self._base = RectCommandBase
        self.main = main
        self.viewer = main.image_viewer
        self.scene = self.viewer._scene
        self.properties = RectCommandBase.save_txt_item_properties(item)

    def redo(self):
        item = self._base.find_matching_txt_item(self.scene, self.properties)
        if item is None:
            return
        if getattr(self.main, "curr_tblock_item", None) is item:
            self.main.curr_tblock_item = None
        self.scene.removeItem(item)
        if item in self.viewer.text_items:
            self.viewer.text_items.remove(item)
        self.scene.update()

    def undo(self):
        if self._base.find_matching_txt_item(self.scene, self.properties) is None:
            self._base.create_new_txt_item(self.properties, self.viewer)
            self.viewer.refresh_layers()


class RemoveBoxCommand(QUndoCommand):
    """A box with no block behind it (one with a block goes through
    DeleteBoxesCommand, which takes the block with it)."""

    def __init__(self, main, item):
        super().__init__("Delete box")
        from app.ui.commands.base import RectCommandBase

        self._base = RectCommandBase
        self.viewer = main.image_viewer
        self.scene = self.viewer._scene
        self.properties = RectCommandBase.save_rect_properties(item)

    def redo(self):
        item = self._base.find_matching_rect(self.scene, self.properties)
        if item is None:
            return
        self.scene.removeItem(item)
        if item in self.viewer.rectangles:
            self.viewer.rectangles.remove(item)
        if self.viewer.selected_rect is item:
            self.viewer.selected_rect = None
        self.scene.update()

    def undo(self):
        if self._base.find_matching_rect(self.scene, self.properties) is None:
            self._base.create_rect_item(self.properties, self.viewer)
            self.viewer.refresh_layers()
