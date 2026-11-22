"""The Layers panel: the document's groups, and every object on screen as a layer.

Rows are the five fixed groups, topmost first (Editable Text ... Raw Image),
each holding one row per object currently on the canvas (the page on screen, or
the loaded pages in webtoon mode, each object labelled with its page). Listing
every object of a 200-page strip would mean thousands of rows nobody scrolls.

Each row has an eye (visible), a lock and a name. Clicking the eye or lock of a
group row changes that group across the whole document; on an object row it
changes that object only, as an undo step. Double-click an object's name to
rename it. The slider sets opacity for the selected rows, and the arrows move
the selected object up or down within its group. Picking a text or box row
selects it on the canvas; a patch or stroke row is framed there. The trash
button (or Delete) takes the selected objects off the page as one undo step —
one patch of a Clean, say, without undoing the rest.

The panel owns no state. It is rebuilt from the scene whenever layers, the undo
stack or the page change (coalesced into one rebuild per event-loop turn, and
skipped while the panel is hidden), and every edit goes through LayerController.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from app.ui.dayu_widgets.qt import MIcon
from core.layers import DEFAULT_GROUP_NAMES, PAINT_ORDER, LayerGroup

COL_VIS, COL_LOCK, COL_NAME = 0, 1, 2
#: Layer thumbnails, as in Photoshop's Layers panel.
THUMB = QtCore.QSize(36, 26)
ROLE_GROUP = Qt.ItemDataRole.UserRole
ROLE_OBJECT = Qt.ItemDataRole.UserRole + 1


class LayersPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ctrl = None
        self._rebuilding = False
        self._icons = {
            "eye": MIcon("eye.svg"),
            "eye-off": MIcon("eye-off.svg"),
            "lock": MIcon("lock.svg"),
            "lock-open": MIcon("lock-open.svg"),
        }
        self._group_icon = MIcon("folder-open.svg")

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        # Expand arrows and indentation on the name column, so the eye and
        # lock columns stay aligned at the left edge as in an image editor.
        self.tree.setTreePosition(COL_NAME)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(COL_VIS, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_LOCK, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(COL_VIS, 26)
        self.tree.setColumnWidth(COL_LOCK, 26)
        self.tree.setIconSize(THUMB)
        self._thumb_cache: dict[str, tuple[object, QtGui.QIcon]] = {}

        self.opacity_label = QtWidgets.QLabel(self.tr("Opacity"))
        self.opacity_slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setTracking(False)  # one undo step per drag, on release
        self.opacity_value = QtWidgets.QLabel("100%")
        self.opacity_value.setMinimumWidth(36)

        self.up_button = QtWidgets.QToolButton()
        self.up_button.setIcon(MIcon("up_line.svg"))
        self.up_button.setToolTip(self.tr("Move the selected layer up within its group"))
        self.down_button = QtWidgets.QToolButton()
        self.down_button.setIcon(MIcon("down_line.svg"))
        self.down_button.setToolTip(self.tr("Move the selected layer down within its group"))
        self.delete_button = QtWidgets.QToolButton()
        self.delete_button.setIcon(MIcon("trash_line.svg"))
        self.delete_button.setToolTip(self.tr("Delete the selected layers (Delete)"))

        # Photoshop's arrangement: opacity above the list, the layer buttons
        # in a strip below it with the trash at the far right.
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.opacity_label)
        top.addWidget(self.opacity_slider, 1)
        top.addWidget(self.opacity_value)

        bottom = QtWidgets.QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.up_button)
        bottom.addWidget(self.down_button)
        bottom.addSpacing(8)
        bottom.addWidget(self.delete_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addLayout(bottom)

        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.rebuild)

        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.opacity_slider.valueChanged.connect(self._on_opacity_committed)
        self.opacity_slider.sliderMoved.connect(lambda v: self.opacity_value.setText(f"{v}%"))
        self.up_button.clicked.connect(lambda: self._move_selected(+1))
        self.down_button.clicked.connect(lambda: self._move_selected(-1))
        self.delete_button.clicked.connect(self._delete_selected)
        self.tree.installEventFilter(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self._update_controls()

    # --- wiring ------------------------------------------------------------------

    def bind(self, layer_ctrl) -> None:
        self._ctrl = layer_ctrl
        layer_ctrl.layers_changed.connect(self.schedule_refresh)
        layer_ctrl.main.undo_group.indexChanged.connect(self.schedule_refresh)
        layer_ctrl.main.undo_group.activeStackChanged.connect(self.schedule_refresh)
        layer_ctrl.viewer.layers_refreshed.connect(self.schedule_refresh)
        self.schedule_refresh()

    def schedule_refresh(self, *_):
        if self.isVisible():
            self._refresh_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_refresh()

    _DELETE_KEYS = (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)

    def eventFilter(self, obj, event):
        # Delete in the tree deletes layers. The window's own Delete shortcut
        # (delete the selected box) would claim the same key, and two matches
        # fire neither, so the tree takes it first — except while a name is
        # being edited, where the key deletes letters.
        if obj is self.tree and event.type() in (QtCore.QEvent.Type.ShortcutOverride,
                                                 QtCore.QEvent.Type.KeyPress):
            if (event.key() in self._DELETE_KEYS and not event.modifiers()
                    and self.tree.state() != QtWidgets.QAbstractItemView.State.EditingState):
                event.accept()
                if event.type() == QtCore.QEvent.Type.KeyPress:
                    self._delete_selected()
                return True
        return super().eventFilter(obj, event)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._ctrl is not None:
            self._ctrl.clear_highlight()

    # --- building ----------------------------------------------------------------

    def _group_label(self, group: LayerGroup) -> str:
        # Literal tr() calls so lupdate can see them; the English matches
        # core.layers.DEFAULT_GROUP_NAMES (and the PSD export's group names).
        labels = {
            LayerGroup.TEXT: self.tr("Editable Text"),
            LayerGroup.BOXES: self.tr("Boxes"),
            LayerGroup.STROKES: self.tr("Brush Strokes"),
            LayerGroup.PATCHES: self.tr("Inpaint Patches"),
            LayerGroup.RAW: self.tr("Raw Image"),
        }
        return labels.get(group, DEFAULT_GROUP_NAMES[group])

    def _default_object_name(self, group: LayerGroup, item, number: int) -> str:
        if group is LayerGroup.TEXT and hasattr(item, "toPlainText"):
            text = " ".join(item.toPlainText().split())
            if text:
                return text if len(text) <= 32 else text[:31] + "…"
            return self.tr("Text")
        base = {
            LayerGroup.BOXES: self.tr("Box"),
            LayerGroup.STROKES: self.tr("Stroke"),
            LayerGroup.PATCHES: self.tr("Patch"),
        }.get(group, self.tr("Layer"))
        return f"{base} {number}"

    def _page_suffix(self, item) -> str:
        viewer = self._ctrl.viewer
        if not getattr(viewer, "webtoon_mode", False):
            return ""
        layout = getattr(getattr(viewer, "webtoon_manager", None), "layout_manager", None)
        if layout is None:
            return ""
        idx = layout.get_page_at_position(item.sceneBoundingRect().center().y())
        return f"  · p{idx + 1}"

    # --- thumbnails ------------------------------------------------------------

    @staticmethod
    def _thumb_key(item):
        """What a thumbnail depends on: when it is unchanged, the cached one is reused."""
        rect = item.boundingRect()
        geometry = (round(rect.width(), 1), round(rect.height(), 1))
        if isinstance(item, QtWidgets.QGraphicsPixmapItem):
            return ("pixmap", item.pixmap().cacheKey(), geometry)
        if isinstance(item, QtWidgets.QGraphicsPathItem):
            path = item.path()
            return ("path", path.elementCount(), geometry, item.pen().color().rgba(), item.brush().color().rgba())
        if hasattr(item, "document"):
            extra = tuple(str(getattr(item, name, "")) for name in
                          ("selection_outlines", "stroke_layers", "shadow_enabled", "gradient_enabled"))
            return ("text", hash(item.document().toHtml()), geometry, extra)
        return ("item", type(item).__name__, geometry)

    @staticmethod
    def _checkerboard(painter: QtGui.QPainter, size: QtCore.QSize) -> None:
        light, dark = QtGui.QColor("#f2f2f2"), QtGui.QColor("#d4d4d4")
        cell = 5
        for y in range(0, size.height(), cell):
            for x in range(0, size.width(), cell):
                painter.fillRect(x, y, cell, cell, light if (x // cell + y // cell) % 2 == 0 else dark)

    def _render_thumbnail(self, item) -> QtGui.QIcon:
        """The item drawn small over a checkerboard (transparency), as in an image editor."""
        ratio = self.devicePixelRatioF() or 1.0
        pixmap = QtGui.QPixmap(int(THUMB.width() * ratio), int(THUMB.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            self._checkerboard(painter, THUMB)
            rect = item.boundingRect()
            if rect.width() > 0 and rect.height() > 0:
                scale = min((THUMB.width() - 2) / rect.width(), (THUMB.height() - 2) / rect.height())
                painter.translate(THUMB.width() / 2, THUMB.height() / 2)
                painter.scale(scale, scale)
                painter.translate(-rect.center())
                # Text and boxes draw their selection frame and handles while
                # selected; a thumbnail shows the layer, not the selection.
                was_selected = getattr(item, "selected", None)
                if was_selected:
                    item.selected = False
                try:
                    item.paint(painter, QtWidgets.QStyleOptionGraphicsItem(), None)
                finally:
                    if was_selected:
                        item.selected = was_selected
        except Exception:  # noqa: BLE001 — a thumbnail is decoration; never break the panel
            pass
        finally:
            painter.end()
        return QtGui.QIcon(pixmap)

    def _thumbnail(self, key: str, item) -> QtGui.QIcon:
        stamp = self._thumb_key(item)
        cached = self._thumb_cache.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        icon = self._render_thumbnail(item)
        self._thumb_cache[key] = (stamp, icon)
        return icon

    def _set_state_icons(self, row, visible: bool, locked: bool, lockable: bool = True):
        row.setIcon(COL_VIS, self._icons["eye" if visible else "eye-off"])
        row.setToolTip(COL_VIS, (self.tr("Hide") if visible else self.tr("Show"))
                       + "\n" + self.tr("Alt+click: show only this"))
        if lockable:
            row.setIcon(COL_LOCK, self._icons["lock" if locked else "lock-open"])
            row.setToolTip(COL_LOCK, self.tr("Unlock") if locked else self.tr("Lock"))

    def rebuild(self) -> None:
        if self._ctrl is None:
            return
        doc = self._ctrl.document()
        selected = {r.data(COL_NAME, ROLE_OBJECT) or r.data(COL_NAME, ROLE_GROUP)
                    for r in self.tree.selectedItems()}
        expanded = {self.tree.topLevelItem(i).data(COL_NAME, ROLE_GROUP)
                    for i in range(self.tree.topLevelItemCount())
                    if self.tree.topLevelItem(i).isExpanded()}
        first_build = self.tree.topLevelItemCount() == 0

        by_group: dict[LayerGroup, list] = {g: [] for g in LayerGroup}
        for group, oid, item in self._ctrl.page_objects():
            by_group[group].append((oid, item))

        self._rebuilding = True
        self.tree.setUpdatesEnabled(False)
        seen_thumbs: set[str] = set()
        try:
            self.tree.clear()
            for group in reversed(PAINT_ORDER):  # topmost first, like an editor
                gprops = doc.group(group)
                grow = QtWidgets.QTreeWidgetItem(self.tree)
                members = by_group[group]
                label = self._group_label(group)
                grow.setText(COL_NAME, f"{label} ({len(members)})" if group is not LayerGroup.RAW else label)
                grow.setData(COL_NAME, ROLE_GROUP, group.value)
                font = grow.font(COL_NAME)
                font.setBold(True)
                grow.setFont(COL_NAME, font)
                self._set_state_icons(grow, gprops.visible, gprops.locked,
                                      lockable=group is not LayerGroup.RAW)
                photo = getattr(self._ctrl.viewer, "photo", None)
                if group is LayerGroup.RAW and photo is not None and not photo.pixmap().isNull():
                    grow.setIcon(COL_NAME, self._thumbnail("__page__", photo))
                    seen_thumbs.add("__page__")
                else:
                    grow.setIcon(COL_NAME, self._group_icon)

                # scene.items() is topmost-first, the order an editor lists layers.
                count = len(members)
                for i, (oid, item) in enumerate(members):
                    props = self._ctrl.object_props(oid)
                    orow = QtWidgets.QTreeWidgetItem(grow)
                    name = props.name or self._default_object_name(group, item, count - i)
                    orow.setText(COL_NAME, name + self._page_suffix(item))
                    orow.setData(COL_NAME, ROLE_OBJECT, oid)
                    orow.setData(COL_NAME, ROLE_GROUP, group.value)
                    orow.setFlags(orow.flags() | Qt.ItemFlag.ItemIsEditable)
                    self._set_state_icons(orow, props.visible, props.locked)
                    orow.setIcon(COL_NAME, self._thumbnail(oid, item))
                    seen_thumbs.add(oid)
                    if not gprops.visible or not props.visible:
                        # Shown greyed while it is not on the canvas, whether
                        # it or its whole group is hidden.
                        orow.setForeground(COL_NAME, self.palette().brush(
                            QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text))
                    # The column is narrow and elides; the tooltip has it all.
                    tip = name
                    if props.opacity < 1.0:
                        tip += "\n" + self.tr("Opacity") + f" {round(props.opacity * 100)}%"
                    orow.setToolTip(COL_NAME, tip)
                    if oid in selected:
                        orow.setSelected(True)
                if first_build or group.value in expanded:
                    grow.setExpanded(group is not LayerGroup.RAW)
                if group.value in selected:
                    grow.setSelected(True)
        finally:
            self.tree.setUpdatesEnabled(True)
            self._rebuilding = False
        for stale in set(self._thumb_cache) - seen_thumbs:
            del self._thumb_cache[stale]
        self._update_controls()

    # --- reactions ---------------------------------------------------------------

    @staticmethod
    def _row_target(row):
        oid = row.data(COL_NAME, ROLE_OBJECT)
        group = LayerGroup(row.data(COL_NAME, ROLE_GROUP))
        return oid, group

    def _on_item_clicked(self, row, column):
        if self._ctrl is None or column not in (COL_VIS, COL_LOCK):
            return
        oid, group = self._row_target(row)
        # Alt+click on an eye shows that layer (or group) alone; again, and
        # everything is back. The quick way to see what one patch covers.
        alt = bool(QtWidgets.QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)
        if alt and column == COL_VIS:
            if oid is None:
                self._ctrl.solo_group(group)
            else:
                self._ctrl.solo(oid, text=self.tr("Show only this layer"))
            return
        if oid is None:
            gprops = self._ctrl.document().group(group)
            if column == COL_VIS:
                self._ctrl.set_group_props(group, visible=not gprops.visible)
            elif group is not LayerGroup.RAW:
                self._ctrl.set_group_props(group, locked=not gprops.locked)
            return
        props = self._ctrl.object_props(oid)
        if props is None:
            return
        if column == COL_VIS:
            self._ctrl.set_object_props([oid], text=self.tr("Toggle layer visibility"),
                                        visible=not props.visible)
        else:
            self._ctrl.set_object_props([oid], text=self.tr("Toggle layer lock"),
                                        locked=not props.locked)

    def _show_context_menu(self, pos):
        """Right-click on a row: what the eye, the lock and the buttons do,
        plus showing one layer alone, in one place."""
        row = self.tree.itemAt(pos)
        if row is None or self._ctrl is None:
            return
        if not row.isSelected():
            self.tree.setCurrentItem(row)
        menu = self._build_context_menu(row)
        if menu is not None:
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _build_context_menu(self, row):
        oid, group = self._row_target(row)
        menu = QtWidgets.QMenu(self)
        if oid is None:
            gprops = self._ctrl.document().group(group)
            menu.addAction(self.tr("Hide Group") if gprops.visible else self.tr("Show Group"),
                           lambda: self._ctrl.set_group_props(group, visible=not gprops.visible))
            if group is not LayerGroup.RAW:
                menu.addAction(self.tr("Show Only This Group"), lambda: self._ctrl.solo_group(group))
                menu.addAction(self.tr("Unlock Group") if gprops.locked else self.tr("Lock Group"),
                               lambda: self._ctrl.set_group_props(group, locked=not gprops.locked))
        else:
            props = self._ctrl.object_props(oid)
            if props is None:
                return None
            ids = [o for o, _g in self._selected_targets() if o] or [oid]
            menu.addAction(self.tr("Hide") if props.visible else self.tr("Show"),
                           lambda: self._ctrl.set_object_props(
                               ids, text=self.tr("Toggle layer visibility"), visible=not props.visible))
            menu.addAction(self.tr("Show Only This Layer"),
                           lambda: self._ctrl.solo(oid, text=self.tr("Show only this layer")))
            menu.addAction(self.tr("Unlock") if props.locked else self.tr("Lock"),
                           lambda: self._ctrl.set_object_props(
                               ids, text=self.tr("Toggle layer lock"), locked=not props.locked))
            menu.addSeparator()
            menu.addAction(self.tr("Rename"), lambda: self.tree.editItem(row, COL_NAME))
            menu.addAction(self.tr("Delete"), self._delete_selected)
        return menu

    def _on_item_changed(self, row, column):
        if self._rebuilding or self._ctrl is None or column != COL_NAME:
            return
        oid, _group = self._row_target(row)
        if oid is None:
            return
        text = row.text(COL_NAME).split("  · p")[0].strip()
        self._ctrl.set_object_props([oid], text=self.tr("Rename layer"), name=text)

    def _selected_targets(self):
        return [self._row_target(r) for r in self.tree.selectedItems()]

    def _on_selection_changed(self):
        if self._rebuilding:
            return
        self._update_controls()
        targets = self._selected_targets()
        if self._ctrl is None:
            return
        if len(targets) == 1 and targets[0][0]:
            self._ctrl.select_on_canvas(targets[0][0])
        else:
            self._ctrl.clear_highlight()

    def _update_controls(self):
        targets = self._selected_targets() if self._ctrl is not None else []
        has = bool(targets)
        self.opacity_slider.setEnabled(has)
        one_object = len(targets) == 1 and targets[0][0] is not None
        self.up_button.setEnabled(one_object)
        self.down_button.setEnabled(one_object)
        self.delete_button.setEnabled(any(oid for oid, _group in targets))
        if not has:
            return
        oid, group = targets[0]
        if oid is None:
            value = self._ctrl.document().group(group).opacity
        else:
            props = self._ctrl.object_props(oid)
            value = props.opacity if props is not None else 1.0
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(round(value * 100))
        self.opacity_slider.blockSignals(False)
        self.opacity_value.setText(f"{round(value * 100)}%")

    def _on_opacity_committed(self, value: int):
        if self._ctrl is None:
            return
        self.opacity_value.setText(f"{value}%")
        opacity = value / 100.0
        targets = self._selected_targets()
        object_ids = [oid for oid, _g in targets if oid]
        for oid, group in targets:
            if oid is None:
                self._ctrl.set_group_props(group, opacity=opacity)
        if object_ids:
            self._ctrl.set_object_props(object_ids, text=self.tr("Change layer opacity"),
                                        opacity=opacity)

    def _move_selected(self, direction: int):
        targets = self._selected_targets()
        if self._ctrl is None or len(targets) != 1 or targets[0][0] is None:
            return
        oid, _group = targets[0]
        row = self.tree.selectedItems()[0]
        parent = row.parent()
        ids_top_first = [parent.child(i).data(COL_NAME, ROLE_OBJECT) for i in range(parent.childCount())]
        i = ids_top_first.index(oid)
        j = i - direction  # "up" means towards the top of the list
        if not 0 <= j < len(ids_top_first):
            return
        ids_top_first[i], ids_top_first[j] = ids_top_first[j], ids_top_first[i]
        self._ctrl.reorder(list(reversed(ids_top_first)))

    def _delete_selected(self):
        if self._ctrl is None:
            return
        object_ids = [oid for oid, _group in self._selected_targets() if oid]
        if object_ids:
            self._ctrl.delete_objects(object_ids, text=self.tr("Delete layers"))
