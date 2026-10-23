"""Which way a block's lines run, and where they are cut, before OCR reads them.

Found on real English and Korean webtoon pages where local OCR returned
"! • • IT.. BU BL" for "BUT...!" (the block was split into columns and each
read rotated, right to left), "1 BUT. ••••" once it was rows (the "!", a
pixel higher, was read first), and "HIS CHAPTER IS TRANSLATE UACOMIC.ORG…"
for a centred caption whose first and last letters were cut off as columns.
"""

import types

import numpy as np
import pytest

from modules.detection.heuristic_lines import relayout_for_language
from modules.detection.heuristic_lines.clustering import _absorb_glyph_fragments, _join_same_row_pieces
from modules.detection.heuristic_lines.core import _detect_lines_and_direction_in_crop
from modules.detection.heuristic_lines.direction import writes_vertically
from modules.detection.heuristic_lines.mask import _split_mask_by_tall_vertical_columns
from modules.ocr import processor as ocr_processor
from modules.utils.textblock import TextBlock


def as_crop(mask):
    """A binary mask (True = ink) as a black-on-white RGB crop."""
    return np.repeat((255 - mask.astype(np.uint8) * 255)[..., None], 3, axis=2)


def glyph_columns(n_cols=2, n_glyphs=5, glyph=28, gap_y=8, gap_x=22, pad=10):
    """Square, CJK-like glyphs stacked in columns: a crop that reads as columns."""
    width = 2 * pad + n_cols * glyph + (n_cols - 1) * gap_x
    height = 2 * pad + n_glyphs * glyph + (n_glyphs - 1) * gap_y
    mask = np.zeros((height, width), bool)
    for c in range(n_cols):
        for g in range(n_glyphs):
            x, y = pad + c * (glyph + gap_x), pad + g * (glyph + gap_y)
            mask[y:y + glyph + 1, x:x + glyph + 1] = True
            mask[y + 4:y + glyph - 3, x + 4:x + glyph - 3] = False
            mask[y:y + glyph + 1, x + glyph // 2 - 2:x + glyph // 2 + 2] = True
            mask[y + glyph // 2 - 1:y + glyph // 2 + 2, x:x + glyph + 1] = True
    return mask


class TestLanguageDecidesColumns:
    @pytest.mark.parametrize("language, expected", [
        ("Japanese", True), ("ja", True), ("Chinese", True), ("zh-CN", True),
        ("Korean", False), ("ko", False), ("English", False), ("en", False), ("fr", False),
        ("", None), (None, None),
    ])
    def test_which_languages_are_set_in_columns(self, language, expected):
        assert writes_vertically(language) is expected

    @pytest.mark.parametrize("language", ["English", "Korean"])
    def test_a_language_without_columns_is_read_as_rows(self, language):
        lines, direction = _detect_lines_and_direction_in_crop(as_crop(glyph_columns()), language)
        assert direction == "horizontal"
        assert len(lines) == 5
        assert [line[1] for line in lines] == sorted(line[1] for line in lines)

    @pytest.mark.parametrize("language", ["Japanese", "zh", ""])
    def test_columns_stay_columns_where_they_can_be_meant(self, language):
        lines, direction = _detect_lines_and_direction_in_crop(as_crop(glyph_columns()), language)
        assert (direction, len(lines)) == ("vertical", 2)


def column_block(image, x, y, source_lang):
    crop = as_crop(glyph_columns())
    h, w = crop.shape[:2]
    image[y:y + h, x:x + w] = crop
    blk = TextBlock(text_bbox=np.array([x, y, x + w, y + h]))
    blk.direction = "vertical"
    blk.lines = [[x, y, x + w // 2, y + h], [x + w // 2, y, x + w, y + h]]
    blk.source_lang = source_lang
    return blk


class TestRelayoutAtOcr:
    """Detection splits lines before the language is known; OCR redoes them."""

    def test_a_block_split_into_columns_is_redone_as_rows(self):
        image = np.full((450, 450, 3), 255, np.uint8)
        english = column_block(image, 20, 20, "en")
        japanese = column_block(image, 220, 20, "ja")
        unknown = column_block(image, 20, 220, "")
        kept = [list(map(list, b.lines)) for b in (japanese, unknown)]

        assert relayout_for_language(image, [english, japanese, unknown]) == [english]
        assert english.direction == "horizontal" and len(english.lines) == 5
        assert [list(map(list, b.lines)) for b in (japanese, unknown)] == kept
        assert japanese.direction == unknown.direction == "vertical"

    def test_ocr_reads_the_rows(self, monkeypatch):
        image = np.full((300, 300, 3), 255, np.uint8)
        blk = column_block(image, 20, 20, "")
        seen = {}

        class Engine:
            def process_image(self, img, blk_list):
                seen["lines"] = [(b.direction, len(b.lines)) for b in blk_list]
                return blk_list

        monkeypatch.setattr(ocr_processor.OCRFactory, "create_engine", staticmethod(lambda *a, **k: Engine()))
        proc = ocr_processor.OCRProcessor()
        proc.settings = types.SimpleNamespace()
        proc.source_lang_english = "English"
        proc.ocr_key = "Default"
        proc.process(image, [blk])
        assert seen["lines"] == [("horizontal", 5)]


def thin_letter(mask, x1, x2, y, height=30, stroke=3):
    """A capital in thin strokes, an 'E': three bars and a stem."""
    for bar in (y, y + height // 2 - stroke // 2, y + height - stroke):
        mask[bar:bar + stroke, x1:x2] = True
    mask[y:y + height, x1:x1 + stroke] = True


# Four centred lines of capitals, letter by letter (x1, x2). The long lines'
# first and last letters stand at the same x on every line, so the 1-2 px gaps
# after them line up down the whole caption — the shape of the real
# "THIS CHAPTER IS TRANSLATED / BY LUACOMIC.ORG TEAM READ ON / …".
CAPTION = [
    [(62, 79), (81, 94), (97, 111), (122, 138), (141, 158), (161, 173), (176, 192), (195, 205),
     (208, 218), (221, 237), (240, 252), (255, 265), (276, 289), (292, 309), (312, 323), (326, 336),
     (339, 351), (354, 369), (372, 389), (392, 409), (416, 435)],
    [(19, 34), (36, 60), (62, 79), (81, 93), (96, 109), (120, 134), (137, 150), (153, 169), (172, 185),
     (188, 198), (201, 213), (216, 226), (229, 240), (243, 257), (260, 274), (277, 291), (294, 304),
     (307, 318), (321, 337), (348, 364), (367, 379), (390, 401), (404, 414), (416, 435), (437, 470),
     (472, 488)],
    [(19, 34), (36, 60), (62, 79), (81, 97), (100, 114), (125, 137), (140, 152), (155, 170), (173, 186),
     (189, 200), (203, 220), (231, 248), (251, 263), (266, 283), (286, 303), (306, 316), (319, 336),
     (339, 355), (358, 370), (373, 384), (387, 403), (416, 435), (437, 470)],
    [(150, 166), (169, 182), (185, 196), (199, 209), (220, 235), (238, 252), (255, 265), (268, 282),
     (285, 295), (298, 308), (311, 326), (329, 340)],
]


def caption_mask():
    mask = np.zeros((4 * 32 + 20, 500), bool)
    for row, letters in enumerate(CAPTION):
        for x1, x2 in letters:
            thin_letter(mask, x1, x2, 10 + row * 32)
    return mask


def caption_with_a_side_column(gap=30, lower=16):
    """The caption's left part, and beside it a column of three short lines of
    its own, set half a line lower than the caption's."""
    mask = np.zeros((4 * 32 + 20 + lower, 560), bool)
    for row, letters in enumerate(CAPTION):
        for x1, x2 in letters:
            if x2 <= 414:
                thin_letter(mask, x1, x2, 10 + row * 32)
    for row in range(3):
        y, x = 10 + lower + row * 32, 414 + gap
        for w in (16, 14, 18):
            mask[y:y + 30, x:x + w] = True
            mask[y + 6:y + 24, x + w // 2 - 1:x + w // 2 + 1] = False
            x += w + 2
    return mask


class TestColumnGaps:
    def test_a_centred_caption_is_not_cut_into_columns(self):
        assert len(_split_mask_by_tall_vertical_columns(caption_mask())) == 1

    def test_every_line_keeps_its_first_and_last_letters(self):
        lines, direction = _detect_lines_and_direction_in_crop(as_crop(caption_mask()), "English")
        assert direction == "horizontal" and len(lines) == 4
        assert min(line[0] for line in lines) <= 19
        assert max(line[2] for line in lines) >= 488

    def test_a_real_column_beside_the_text_still_splits(self):
        parts = _split_mask_by_tall_vertical_columns(caption_with_a_side_column())
        assert len(parts) == 2
        assert [int(np.where(p.any(axis=0))[0].min()) for p in parts] == [19, 444]


# "BUT...!" as the rows were found on the real page: the "!" (a pixel higher,
# so read first), "BUT", and the dots with the foot of the "!" below them.
BUT = [[155, 16, 168, 56], [15, 17, 109, 56], [103, 48, 167, 69]]


class TestSameRowPieces:
    def test_pieces_side_by_side_become_one_line(self):
        assert _absorb_glyph_fragments(_join_same_row_pieces(BUT)) == [[15, 16, 168, 69]]

    def test_the_two_tall_pieces_join_first(self):
        assert [15, 16, 168, 56] in _join_same_row_pieces(BUT)

    def test_stacked_lines_stay_apart(self):
        lines = [[20, 10, 300, 40], [30, 44, 290, 74], [60, 78, 250, 108]]
        assert _join_same_row_pieces(lines) == lines

    def test_far_apart_on_one_row_stay_apart(self):
        lines = [[0, 10, 60, 40], [200, 10, 260, 40]]
        assert _join_same_row_pieces(lines) == lines

    def test_slanted_lines_are_left_alone(self):
        slanted = [[0, 0], [100, 10], [98, 40], [-2, 30]]
        lines = [[110, 12, 160, 42], slanted]
        assert _join_same_row_pieces(lines) == lines
