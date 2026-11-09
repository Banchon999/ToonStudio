"""An outline whose colour is a hex string saves into a project.

`OutlineInfo.color` is a QColor when the canvas built the outline and a hex
string when the pipeline did (`core.text_style.full_document_outline`, used by
batch rendering). Saving a project with a batch-rendered page crashed in
`encode_qcolor` with "'str' object has no attribute 'name'".
"""

import msgpack
from PySide6.QtGui import QColor

from app.projects.parsers import ProjectDecoder, ProjectEncoder
from core.text_style import OutlineInfo, OutlineType, full_document_outline


def _round_trip(value):
    packed = msgpack.packb(value, default=ProjectEncoder().encode, use_bin_type=True)
    return msgpack.unpackb(packed, object_hook=ProjectDecoder().decode, strict_map_key=True)


def test_an_outline_with_a_hex_string_colour_saves_and_loads_as_a_qcolor():
    outlines = full_document_outline("สวัสดี", "#ff112233", 2.5)
    state = {"text_items_state": [{"selection_outlines": outlines}]}
    (back,) = _round_trip(state)["text_items_state"][0]["selection_outlines"]
    assert isinstance(back.color, QColor) and back.color.name(QColor.NameFormat.HexArgb) == "#ff112233"
    assert (back.start, back.end, back.width, back.type) == (0, 6, 2.5, OutlineType.Full_Document)


def test_an_outline_with_a_qcolor_still_round_trips():
    outline = OutlineInfo(1, 4, QColor("#80ffffff"), 3, OutlineType.Selection)
    back = _round_trip([outline])[0]
    assert back.color.name(QColor.NameFormat.HexArgb) == "#80ffffff"


def test_an_outline_with_no_colour_does_not_stop_the_save():
    back = _round_trip([OutlineInfo(0, 2, None, 1, OutlineType.Full_Document)])[0]
    assert isinstance(back.color, QColor)
