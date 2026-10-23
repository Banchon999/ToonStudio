"""Fixing a page after Clean without undoing the whole Clean.

Asked for by the owner, and run first on a real page in a real window:

1. Clean wiped part of a character (a stray mask stroke over a chin). Undo
   would take back every bubble too. The restore eraser already brought the
   chin back exactly, as one undo step; the Layers panel had a row for the
   chin's patch but no way to delete it (no button, Delete did nothing), and
   picking a patch row showed nothing on the canvas, so "Patch 3" could not be
   told from the bubbles' patches.
2. OCR run again after Clean read the cleaned page: "DEPUTY DIRECTOR!" came
   back as "A", "I CANNOT," as nothing. The multi-page OCR already read the
   original page; the single-page and webtoon OCR read the composite.
3. Layers edited for real: delete a patch, a stroke, a text item or a box.
"""

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainterPath
from PySide6.QtWidgets import QApplication


def _pump_until(qapp, condition, timeout_ms=20000):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        qapp.processEvents()
    return condition()


LETTERING = (slice(100, 140), slice(100, 200))


@pytest.fixture
def window(qapp, tmp_path):
    from PIL import Image

    import controller as controller_mod

    win = controller_mod.ComicTranslate()
    page = np.full((200, 300, 3), 200, np.uint8)
    page[LETTERING] = 20                  # the "lettering" Clean removes
    page[10:40, 20:80] = (180, 120, 100)  # "artwork" a stray clean wipes
    path = str(tmp_path / "page.png")
    Image.fromarray(page).save(path)
    win.image_ctrl.thread_load_images([path])
    assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto() and win.undo_group.activeStack() is not None)
    yield win
    win._skip_close_prompt = True
    win.close()


def composite(win):
    return win.image_viewer.get_image_array(include_patches=True)


def clean(win, bbox, colour=200):
    """Put a patch where Clean would, as one undo step."""
    from app.ui.commands.inpaint import PatchInsertCommand

    x, y, w, h = bbox
    cmd = PatchInsertCommand(win, [{"bbox": [x, y, w, h], "image": np.full((h, w, 3), colour, np.uint8)}],
                             win.image_files[0])
    win.undo_group.activeStack().push(cmd)
    return cmd.properties_list[0]["object_id"]


def add_box(win, xyxy):
    from modules.utils.textblock import TextBlock

    x1, y1, x2, y2 = xyxy
    blk = TextBlock(text_bbox=np.array(xyxy))
    win.blk_list.append(blk)
    win.image_viewer.add_rectangle(QRectF(0, 0, x2 - x1, y2 - y1), QPointF(x1, y1))
    return blk


class TestOcrAfterClean:
    def capture_ocr(self, monkeypatch):
        from modules.ocr.processor import OCRProcessor

        seen = []
        monkeypatch.setattr(OCRProcessor, "initialize", lambda self, main, lang: None)

        def process(self, image, blk_list):
            seen.append(image.copy())
            for blk in blk_list:
                blk.text = "read"
            return blk_list

        monkeypatch.setattr(OCRProcessor, "process", process)
        return seen

    def test_ocr_reads_the_lettering_under_the_cleaned_patch(self, window, monkeypatch):
        add_box(window, [100, 100, 200, 140])
        clean(window, (95, 95, 110, 50))
        assert (composite(window)[120, 150] == 200).all(), "the lettering was cleaned"
        seen = self.capture_ocr(monkeypatch)
        window.pipeline.OCR_image()
        assert seen, "OCR ran"
        assert (seen[0][LETTERING] == 20).all(), "OCR was handed the page with its lettering"
        assert window.blk_list[0].text == "read"

    def test_ocr_in_webtoon_mode_reads_the_lettering_too(self, qapp, tmp_path, monkeypatch):
        from PIL import Image

        import controller as controller_mod
        from modules.utils.textblock import TextBlock

        win = controller_mod.ComicTranslate()
        try:
            win.resize(1200, 800)
            win.show()
            paths = []
            for index in range(2):
                page = np.full((300, 240, 3), 200, np.uint8)
                page[100:130, 60:180] = 20
                path = str(tmp_path / f"{index:03d}.png")
                Image.fromarray(page).save(path)
                paths.append(path)
            win.image_ctrl.thread_load_images(paths)
            assert _pump_until(qapp, lambda: win.image_viewer.hasPhoto() and len(win.image_files) == 2)
            win.show_main_page()
            win.webtoon_toggle.click()
            viewer = win.image_viewer
            assert _pump_until(qapp, lambda: viewer.webtoon_mode and len(viewer.webtoon_manager.loaded_pages) == 2)
            viewer.centerOn(120, 150)
            qapp.processEvents()
            _, mappings = viewer.get_visible_area_image()
            page_one = next(m for m in mappings if m["page_index"] == 0)
            top = page_one["scene_y_start"]

            # A cleaned patch over page one's lettering, drawn where it is.
            from app.ui.commands.inpaint import PatchInsertCommand

            x_off = viewer.webtoon_manager.layout_manager.get_page_x_offset(0) \
                if hasattr(viewer.webtoon_manager.layout_manager, "get_page_x_offset") else 0
            cmd = PatchInsertCommand(win, [{"bbox": [55, 95, 130, 40], "image": np.full((40, 130, 3), 200, np.uint8),
                                            "scene_pos": [55 + x_off, top + 95], "page_index": 0}], win.image_files[0])
            win.undo_group.activeStack().push(cmd)
            win.blk_list = [TextBlock(text_bbox=np.array([60 + x_off, top + 100, 180 + x_off, top + 130]))]
            cleaned, _ = viewer.get_visible_area_image()
            seen = self.capture_ocr(monkeypatch)
            win.pipeline.OCR_webtoon_visible_area()
            assert seen, "OCR ran"
            image = seen[0]
            row = int(page_one["combined_y_start"] + 115) if "combined_y_start" in page_one else 115
            assert image[row].min() == 20, "the visible page reached OCR with its lettering"
            assert cleaned[row].min() > 20, "while the composite shows it cleaned"
        finally:
            win._skip_close_prompt = True
            win.close()


class TestDeleteLayers:
    def test_deleting_one_patch_undoes_that_part_of_the_clean_only(self, window):
        raw = window.image_viewer.get_image_array(include_patches=False).copy()
        bubble = clean(window, (95, 95, 110, 50))
        face = clean(window, (15, 5, 70, 40), colour=230)
        stack = window.undo_group.activeStack()
        steps = stack.count()

        assert window.layer_ctrl.delete_objects([face]) == 1
        after = composite(window)
        assert np.array_equal(after[5:45, 15:85], raw[5:45, 15:85]), "the face is back"
        assert (after[LETTERING] == 200).all(), "the bubble stays cleaned"
        assert stack.count() == steps + 1
        ids = [p["object_id"] for p in window.image_patches[window.image_files[0]]]
        assert ids == [bubble], "and the project no longer stores it"

        stack.undo()
        assert (composite(window)[20, 50] == 230).all()
        assert len(window.image_patches[window.image_files[0]]) == 2
        stack.redo()
        assert np.array_equal(composite(window)[5:45, 15:85], raw[5:45, 15:85])

    def test_a_deleted_patch_stays_deleted_in_the_saved_project(self, window, tmp_path):
        from app.projects.project_state_v2 import load_state_from_proj_file_v2, save_state_to_proj_file_v2

        bubble = clean(window, (95, 95, 110, 50))
        face = clean(window, (15, 5, 70, 40), colour=230)
        window.layer_ctrl.delete_objects([face])
        proj = tmp_path / "fixed.ctpr"
        save_state_to_proj_file_v2(window, str(proj))
        window.image_patches = {}
        load_state_from_proj_file_v2(window, str(proj))
        (entries,) = window.image_patches.values()
        assert [p["object_id"] for p in entries] == [bubble]

    def test_a_text_item_goes_and_its_block_stays(self, window):
        from app.ui.canvas.text.text_item_properties import TextItemProperties

        blk = add_box(window, [100, 100, 200, 140])
        blk.translation = "แปลแล้ว"
        item = window.image_viewer.add_text_item(TextItemProperties(
            text="แปลแล้ว", position=(100, 100), width=100,
            text_color=QColor("#101010"), outline_color=QColor("#ffffff")))
        assert window.layer_ctrl.delete_objects([item.object_id]) == 1
        assert item not in window.image_viewer.text_items
        assert window.blk_list == [blk] and blk.translation == "แปลแล้ว"
        window.undo_group.activeStack().undo()
        assert len(window.image_viewer.text_items) == 1

    def test_a_stroke_goes(self, window):
        from app.ui.canvas.scene_registry import object_id_of

        path = QPainterPath()
        path.addRect(QRectF(10, 10, 50, 30))
        stroke = window.image_viewer.drawing_manager.add_region_stroke(path)
        oid = object_id_of(stroke) or window.layer_ctrl.page_objects()[0][1]
        assert window.layer_ctrl.delete_objects([oid]) == 1
        assert not window.image_viewer.drawing_manager.has_drawn_elements()
        window.undo_group.activeStack().undo()
        assert window.image_viewer.drawing_manager.has_drawn_elements()

    def test_a_box_goes_with_its_block(self, window):
        add_box(window, [100, 100, 200, 140])
        rect = window.image_viewer.rectangles[0]
        assert window.layer_ctrl.delete_objects([rect.object_id]) == 1
        assert window.image_viewer.rectangles == [] and window.blk_list == []
        window.undo_group.activeStack().undo()
        assert len(window.image_viewer.rectangles) == 1 and len(window.blk_list) == 1

    def test_a_locked_layer_is_kept(self, window):
        face = clean(window, (15, 5, 70, 40), colour=230)
        window.layer_ctrl.set_object_props([face], locked=True)
        assert window.layer_ctrl.delete_objects([face]) == 0
        assert len(window.image_patches[window.image_files[0]]) == 1

    def test_several_deletions_are_one_undo_step(self, window):
        a = clean(window, (95, 95, 110, 50))
        b = clean(window, (15, 5, 70, 40), colour=230)
        stack = window.undo_group.activeStack()
        steps = stack.count()
        assert window.layer_ctrl.delete_objects([a, b]) == 2
        assert stack.count() == steps + 1
        stack.undo()
        assert len(window.image_patches[window.image_files[0]]) == 2


class TestLayersPanel:
    def open_panel(self, qapp, win):
        win.show()
        if not win.layers_button.isChecked():
            win.layers_button.click()
        panel = win.layers_panel
        assert _pump_until(qapp, lambda: panel.isVisible())
        panel.rebuild()
        return panel

    def row_for(self, panel, object_id):
        from app.ui.layers_panel import COL_NAME, ROLE_OBJECT

        for i in range(panel.tree.topLevelItemCount()):
            group = panel.tree.topLevelItem(i)
            for j in range(group.childCount()):
                if group.child(j).data(COL_NAME, ROLE_OBJECT) == object_id:
                    return group.child(j)
        return None

    def test_picking_a_patch_row_frames_it_on_the_canvas(self, qapp, window):
        from app.ui.canvas.scene_registry import kind_of

        face = clean(window, (15, 5, 70, 40), colour=230)
        panel = self.open_panel(qapp, window)
        before = composite(window).copy()
        self.row_for(panel, face).setSelected(True)
        frame = window.image_viewer._layer_highlight
        assert frame.isVisible() and frame.rect() == QRectF(15, 5, 70, 40)
        assert kind_of(frame) is None, "the frame is not a layer"
        assert np.array_equal(composite(window), before), "nor part of the page"
        panel.tree.clearSelection()
        assert not frame.isVisible()

    def test_the_frame_goes_when_the_panel_closes_or_the_page_changes(self, qapp, window):
        face = clean(window, (15, 5, 70, 40), colour=230)
        panel = self.open_panel(qapp, window)
        self.row_for(panel, face).setSelected(True)
        frame = window.image_viewer._layer_highlight
        panel.hide()
        assert not frame.isVisible()
        window.image_viewer.clear_scene()
        assert window.image_viewer._layer_highlight is None

    def test_the_delete_button_deletes_the_picked_layer(self, qapp, window):
        bubble = clean(window, (95, 95, 110, 50))
        face = clean(window, (15, 5, 70, 40), colour=230)
        panel = self.open_panel(qapp, window)
        self.row_for(panel, face).setSelected(True)
        assert panel.delete_button.isEnabled()
        panel.delete_button.click()
        ids = [p["object_id"] for p in window.image_patches[window.image_files[0]]]
        assert ids == [bubble]

    def test_delete_in_the_tree_beats_the_windows_delete_box_shortcut(self, qapp, window):
        add_box(window, [100, 100, 200, 140])
        window.image_viewer.select_rectangle(window.image_viewer.rectangles[0])
        face = clean(window, (15, 5, 70, 40), colour=230)
        panel = self.open_panel(qapp, window)
        self.row_for(panel, face).setSelected(True)
        # The override comes first: accepting it is what keeps the window's
        # Delete (delete the selected box) from claiming the key.
        override = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(panel.tree, override)
        assert override.isAccepted()
        QApplication.sendEvent(panel.tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete,
                                                     Qt.KeyboardModifier.NoModifier))
        assert window.image_patches[window.image_files[0]] == []
        assert len(window.image_viewer.rectangles) == 1, "the selected box is still there"

    def test_delete_while_renaming_types_into_the_name(self, qapp, window):
        from app.ui.layers_panel import COL_NAME

        face = clean(window, (15, 5, 70, 40), colour=230)
        panel = self.open_panel(qapp, window)
        row = self.row_for(panel, face)
        row.setSelected(True)
        panel.tree.editItem(row, COL_NAME)
        assert panel.tree.state() == panel.tree.State.EditingState
        override = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        override.ignore()
        QApplication.sendEvent(panel.tree, override)
        assert not override.isAccepted()
        assert len(window.image_patches[window.image_files[0]]) == 1


def test_save_current_image_leaves_the_frame_out(qapp, window, tmp_path):
    import imkit as imk

    face = clean(window, (15, 5, 70, 40), colour=230)
    window.layer_ctrl.select_on_canvas(face)
    assert window.image_viewer._layer_highlight.isVisible()
    out = str(tmp_path / "out.png")
    window.image_ctrl.save_current_image(out)
    saved = imk.read_image(out)
    assert (saved[5:45, 15:85] == 230).all(), "no frame drawn over the patch"
