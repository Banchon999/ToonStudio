"""Settings › Export › Watermark: what is stamped on every exported page.

Holds no state of its own beyond its widgets: `settings()` reads them into a
`core.watermark.WatermarkSettings`, `set_settings()` writes one back, and
`changed` fires on any edit (the settings page autosaves on it). The preview
draws the watermark on a sample page with the same code the export uses.
"""

from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from core.watermark import BOTH, IMAGE, POSITIONS, TEXT, WatermarkSettings

from ..dayu_widgets.check_box import MCheckBox
from ..dayu_widgets.combo_box import MComboBox, MFontComboBox
from ..dayu_widgets.label import MLabel
from .text_rendering_page import ColorPickerButton

# The preview's sample page, a typical manga page's proportions.
PREVIEW_SIZE = (240, 340)


class WatermarkSection(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False

        self.enabled_checkbox = MCheckBox(self.tr("Add a watermark to exported pages"))
        self.enabled_checkbox.setToolTip(self.tr(
            "Stamped on every page when exporting images, CBZ, PDF, ZIP or PSD,\n"
            "and when saving the current page. The project itself is not changed;\n"
            "in a PSD the watermark is a layer of its own."
        ))

        self.kind_options = [
            (TEXT, self.tr("Text")),
            (IMAGE, self.tr("Logo image")),
            (BOTH, self.tr("Logo and text")),
        ]
        self.kind_combo = MComboBox().small()
        for value, label in self.kind_options:
            self.kind_combo.addItem(label, value)

        self.text_input = QtWidgets.QLineEdit()
        self.text_input.setPlaceholderText(self.tr("e.g. your group's name or website"))
        self.font_combo = MFontComboBox().small()
        self.text_size_spin = self._double_spin(0.5, 30.0, 0.5, " %")
        self.text_size_spin.setToolTip(self.tr("Height of the text, as a share of the page's width"))
        self.text_color_button = ColorPickerButton("#ffffff")
        self.outline_color_button = ColorPickerButton("#000000")
        self.outline_spin = self._double_spin(0.0, 20.0, 0.5, " px")
        self.outline_spin.setToolTip(self.tr(
            "Outline around the text, in pixels on a page 1000 px wide (0 = none).\n"
            "It keeps the text readable on both light and dark artwork."
        ))

        self.logo_path_input = QtWidgets.QLineEdit()
        self.logo_path_input.setReadOnly(True)
        self.logo_path_input.setPlaceholderText(self.tr("No logo chosen (PNG with a transparent background works best)"))
        self.logo_browse_button = QtWidgets.QPushButton(self.tr("Choose…"))
        self.logo_clear_button = QtWidgets.QPushButton(self.tr("Remove"))
        self.logo_size_spin = self._double_spin(1.0, 100.0, 1.0, " %")
        self.logo_size_spin.setToolTip(self.tr("Width of the logo, as a share of the page's width"))

        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_value = MLabel("")
        self.position_labels = {
            "top-left": self.tr("Top left"), "top-center": self.tr("Top centre"),
            "top-right": self.tr("Top right"), "middle-left": self.tr("Middle left"),
            "center": self.tr("Centre"), "middle-right": self.tr("Middle right"),
            "bottom-left": self.tr("Bottom left"), "bottom-center": self.tr("Bottom centre"),
            "bottom-right": self.tr("Bottom right"),
        }
        self.position_combo = MComboBox().small()
        for value in POSITIONS:
            self.position_combo.addItem(self.position_labels[value], value)
        self.margin_spin = self._double_spin(0.0, 25.0, 0.5, " %")
        self.margin_spin.setToolTip(self.tr("Distance from the page's edges, as a share of the page's width"))

        self.preview = QtWidgets.QLabel()
        self.preview.setFixedSize(*PREVIEW_SIZE)
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview.setToolTip(self.tr("How the watermark sits on a page"))

        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow(self.tr("Type:"), self.kind_combo)
        self.text_rows = []
        self.text_rows.append(self._row(form, self.tr("Text:"), self.text_input))
        self.text_rows.append(self._row(form, self.tr("Font:"), self.font_combo))
        size_row = QtWidgets.QHBoxLayout()
        size_row.addWidget(self.text_size_spin)
        size_row.addWidget(MLabel(self.tr("Colour")))
        size_row.addWidget(self.text_color_button)
        size_row.addStretch(1)
        self.text_rows.append(self._row(form, self.tr("Text size:"), size_row))
        outline_row = QtWidgets.QHBoxLayout()
        outline_row.addWidget(self.outline_spin)
        outline_row.addWidget(MLabel(self.tr("Colour")))
        outline_row.addWidget(self.outline_color_button)
        outline_row.addStretch(1)
        self.text_rows.append(self._row(form, self.tr("Outline:"), outline_row))
        logo_row = QtWidgets.QHBoxLayout()
        logo_row.addWidget(self.logo_path_input, 1)
        logo_row.addWidget(self.logo_browse_button)
        logo_row.addWidget(self.logo_clear_button)
        self.image_rows = []
        self.image_rows.append(self._row(form, self.tr("Logo:"), logo_row))
        self.image_rows.append(self._row(form, self.tr("Logo size:"), self.logo_size_spin))
        opacity_row = QtWidgets.QHBoxLayout()
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_value)
        form.addRow(self.tr("Opacity:"), opacity_row)
        form.addRow(self.tr("Position:"), self.position_combo)
        form.addRow(self.tr("Distance from edge:"), self.margin_spin)
        self.form = form

        self.options = QtWidgets.QWidget()
        options_layout = QtWidgets.QHBoxLayout(self.options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.addLayout(form, 1)
        options_layout.addWidget(self.preview, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(MLabel(self.tr("Watermark")).h4())
        layout.addWidget(self.enabled_checkbox)
        layout.addWidget(self.options)

        self.logo_browse_button.clicked.connect(self._choose_logo)
        self.logo_clear_button.clicked.connect(self._clear_logo)
        for signal in (
            self.enabled_checkbox.stateChanged, self.kind_combo.currentIndexChanged,
            self.text_input.textChanged, self.font_combo.currentTextChanged,
            self.text_size_spin.valueChanged, self.outline_spin.valueChanged,
            self.logo_size_spin.valueChanged, self.opacity_slider.valueChanged,
            self.position_combo.currentIndexChanged, self.margin_spin.valueChanged,
            self.text_color_button.color_changed, self.outline_color_button.color_changed,
        ):
            signal.connect(self._on_changed)
        self.set_settings(WatermarkSettings())

    # -- building ---------------------------------------------------------------
    @staticmethod
    def _double_spin(low: float, high: float, step: float, suffix: str) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setDecimals(1)
        spin.setSuffix(suffix)
        spin.setFixedWidth(90)
        return spin

    @staticmethod
    def _row(form: QtWidgets.QFormLayout, label: str, field) -> tuple:
        label_widget = MLabel(label)
        if isinstance(field, QtWidgets.QLayout):
            holder = QtWidgets.QWidget()
            field.setContentsMargins(0, 0, 0, 0)
            holder.setLayout(field)
            field = holder
        form.addRow(label_widget, field)
        return label_widget, field

    # -- state ------------------------------------------------------------------
    def settings(self) -> WatermarkSettings:
        return WatermarkSettings.from_dict({
            "enabled": self.enabled_checkbox.isChecked(),
            "kind": self.kind_combo.currentData(),
            "text": self.text_input.text(),
            "font_family": self.font_combo.currentText(),
            "text_size": self.text_size_spin.value(),
            "text_color": self.text_color_button.get_color(),
            "outline_width": self.outline_spin.value(),
            "outline_color": self.outline_color_button.get_color(),
            "image_path": self.logo_path_input.text(),
            "image_size": self.logo_size_spin.value(),
            "opacity": self.opacity_slider.value(),
            "position": self.position_combo.currentData(),
            "margin": self.margin_spin.value(),
        })

    def set_settings(self, settings: WatermarkSettings) -> None:
        self._loading = True
        try:
            self.enabled_checkbox.setChecked(settings.enabled)
            self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(settings.kind)))
            self.text_input.setText(settings.text)
            # No choice yet means the app's own font, which has Thai; show it
            # rather than an empty "please select".
            self.font_combo.setCurrentText(settings.font_family or QtGui.QFont().family())
            self.text_size_spin.setValue(settings.text_size)
            self.text_color_button.set_color(settings.text_color)
            self.outline_spin.setValue(settings.outline_width)
            self.outline_color_button.set_color(settings.outline_color)
            self.logo_path_input.setText(settings.image_path)
            self.logo_size_spin.setValue(settings.image_size)
            self.opacity_slider.setValue(settings.opacity)
            self.position_combo.setCurrentIndex(max(0, self.position_combo.findData(settings.position)))
            self.margin_spin.setValue(settings.margin)
        finally:
            self._loading = False
        self._refresh()

    # -- reactions ----------------------------------------------------------------
    def _on_changed(self, *_args) -> None:
        self._refresh()
        if not self._loading:
            self.changed.emit()

    def _refresh(self) -> None:
        kind = self.kind_combo.currentData()
        for label, field in self.text_rows:
            label.setVisible(kind in (TEXT, BOTH))
            field.setVisible(kind in (TEXT, BOTH))
        for label, field in self.image_rows:
            label.setVisible(kind in (IMAGE, BOTH))
            field.setVisible(kind in (IMAGE, BOTH))
        self.options.setEnabled(self.enabled_checkbox.isChecked())
        self.opacity_value.setText(f"{self.opacity_slider.value()}%")
        self._update_preview()

    def _choose_logo(self) -> None:
        from app.ui.watermark import keep_logo

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, self.tr("Choose a logo"), "", self.tr("Images (*.png *.webp *.jpg *.jpeg *.bmp)"))
        if not path:
            return
        try:
            stored = keep_logo(path)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, self.tr("Watermark"),
                                          self.tr("Could not use that image: {0}").format(exc))
            return
        self.logo_path_input.setText(stored)
        self._on_changed()

    def _clear_logo(self) -> None:
        self.logo_path_input.clear()
        self._on_changed()

    def _update_preview(self) -> None:
        from app.ui.watermark import build_stamp

        width, height = PREVIEW_SIZE
        yy, xx = np.mgrid[:height, :width]
        # A page with light and dark areas, so legibility shows on both.
        page = np.full((height, width, 3), 236, np.uint8)
        page[height // 2:, :] = 70
        page[(xx // 12 + yy // 12) % 2 == 0] -= 12
        settings = self.settings()
        settings.enabled = True
        stamp = build_stamp(settings) if self.enabled_checkbox.isChecked() else None
        if stamp is not None:
            page = stamp.apply(page)
        page = np.ascontiguousarray(page)
        image = QtGui.QImage(page.data, width, height, width * 3, QtGui.QImage.Format.Format_RGB888).copy()
        self.preview.setPixmap(QtGui.QPixmap.fromImage(image))
