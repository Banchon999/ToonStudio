from PySide6 import QtWidgets
from ..dayu_widgets.label import MLabel
from ..dayu_widgets.check_box import MCheckBox

class ExportPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QtWidgets.QVBoxLayout(self)

        batch_label = MLabel(self.tr("Automatic Mode")).h4()
        batch_note = MLabel(
            self.tr(
                "Selected exports are saved to comic_translate_<timestamp> in the same directory as the input file/archive."
            )
        ).secondary()
        batch_note.setWordWrap(True)
        self.raw_text_checkbox = MCheckBox(self.tr("Export Raw Text"))
        self.translated_text_checkbox = MCheckBox(self.tr("Export Translated text"))
        self.inpainted_image_checkbox = MCheckBox(self.tr("Export Inpainted Image"))
        # Editable PSDs written page by page while the batch runs, so a
        # chapter can be reviewed and fixed before the whole run is over.
        self.psd_checkbox = MCheckBox(self.tr(
            "Export PSD of each page as soon as it is translated (a \"<folder>-PSD\" folder beside it)"))

        layout.addWidget(batch_label)
        layout.addWidget(batch_note)
        layout.addWidget(self.raw_text_checkbox)
        layout.addWidget(self.translated_text_checkbox)
        layout.addWidget(self.inpainted_image_checkbox)
        layout.addWidget(self.psd_checkbox)

        layout.addStretch(1)
