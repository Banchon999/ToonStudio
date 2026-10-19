"""How a translation is laid out in its bubble.

Found on real Korean webtoon pages rendered into Thai by Smart Workflow:
lines filled greedily left one word on the last line ("…เข้าไปไม่ได้ / แน่"),
breaks fell wherever pythainlp cut — inside a name it did not know
("ไค / รทอน"), between a word and its particle ("อรุณสวัสดิ์ / ค่ะ") — and
the text was fitted to the source lettering's own tight box and pinned to its
top-left corner, so it came out small and off-centre in an empty bubble.
"""

import numpy as np
import pytest

from core.enums import Alignment
from modules.rendering.render import (
    _segment_no_space_paragraph,
    _wrap_no_space_text_balanced,
    _wrap_text_balanced,
    _wrap_units,
    place_in_area,
    render_area,
    text_position,
)
from modules.utils.textblock import TextBlock


def lines_of(text, width):
    """Balanced Thai wrap with one unit of width per character."""
    return _wrap_no_space_text_balanced([_segment_no_space_paragraph(text)], len, width).split("\n")


class TestThaiBreaks:
    def test_a_particle_stays_with_its_word(self):
        units = [u for u, _ in _wrap_units(_segment_no_space_paragraph("อรุณสวัสดิ์ค่ะ คุณหนู!"))]
        assert units == ["อรุณสวัสดิ์ค่ะ", "คุณหนู!"]

    def test_a_particle_followed_by_punctuation_too(self):
        units = [u for u, _ in _wrap_units(_segment_no_space_paragraph("เหมือนเดิมนะคะ~!"))]
        assert units == ["เหมือนเดิมนะคะ~!"]

    def test_a_name_the_dictionary_does_not_know_is_not_cut(self):
        # pythainlp returns ไค|รท|อน for the name ไครทอน.
        for line in lines_of("ที่เกิดขึ้นกับตระกูลดยุกแห่งไครทอน", 20):
            assert not line.startswith(("รท", "อน")), line
        assert any("ไครทอน" in line for line in lines_of("ที่เกิดขึ้นกับตระกูลดยุกแห่งไครทอน", 20))

    def test_the_name_is_not_glued_to_the_word_before_it(self):
        units = [u for u, _ in _wrap_units(_segment_no_space_paragraph("ตระกูลดยุกไครทาน"))]
        assert units[-1] == "ไครทาน" and "ดยุก" in units

    def test_a_clause_opener_starts_a_line_rather_than_ending_one(self):
        for line in lines_of("ทำให้แม้ไม่มีกองอัศวินในสังกัด ก็ยังมีพลังเทียบเท่ากับกองทัพ", 24):
            assert not line.endswith("ก็"), line

    def test_no_word_is_left_alone_on_the_last_line(self):
        lines = lines_of("จากข้อมูลที่สืบมาได้จนถึงตอนนี้ วิธีทั่วไปคงใช้แทรกซึมเข้าไปไม่ได้แน่", 22)
        assert lines[-1] != "แน่"
        assert max(map(len, lines)) - min(map(len, lines)) <= 8

    def test_a_space_is_where_it_breaks_when_the_lines_allow(self):
        # The greedy wrap ran past the space: "…ในสังกัด ก็ / ยังมี…".
        text = "ทำให้แม้ไม่มีกองอัศวินในสังกัด ก็ยังมีพลังเทียบเท่ากับกองทัพของประเทศเล็กๆ ประเทศหนึ่งได้เลย"
        for width in (32, 36, 40):
            assert lines_of(text, width)[0] == "ทำให้แม้ไม่มีกองอัศวินในสังกัด"

    def test_a_word_too_long_for_any_line_still_wraps(self):
        text = _wrap_no_space_text_balanced([_segment_no_space_paragraph("ประเทศเล็กๆ")], len, 3)
        assert "".join(text.split("\n")) == "ประเทศเล็กๆ"

    def test_strict_refuses_a_size_where_a_word_must_be_cut(self):
        assert _wrap_no_space_text_balanced([_segment_no_space_paragraph("อรุณสวัสดิ์ค่ะ")], len, 5,
                                            strict=True) is None


class TestSpacedBreaks:
    def test_lines_come_out_even(self):
        lines = _wrap_text_balanced("I can't believe you actually came all the way here", len, 30).split("\n")
        assert len(lines) == 2 and abs(len(lines[0]) - len(lines[1])) <= 8

    def test_a_forced_line_break_is_kept(self):
        assert _wrap_text_balanced("ONE\nTWO THREE", len, 40) == "ONE\nTWO THREE"


def block(xyxy, cls="text_bubble", bubble=None, angle=0):
    blk = TextBlock(text_bbox=np.array(xyxy), bubble_bbox=None if bubble is None else np.array(bubble),
                    text_class=cls)
    blk.angle = angle
    return blk


class TestRenderArea:
    def test_a_bubble_to_itself_lends_its_inscribed_rectangle(self):
        blk = block([275, 524, 484, 665], bubble=[160, 400, 600, 855])
        x1, y1, x2, y2 = render_area(blk, [blk])
        assert x1 < 275 and x2 > 484 and y1 < 524 and y2 > 665
        assert x1 >= 160 + 0.14 * 440 and x2 <= 600 - 0.14 * 440

    def test_a_shared_bubble_keeps_the_box(self):
        a = block([200, 450, 300, 500], bubble=[160, 400, 600, 855])
        b = block([300, 700, 500, 780], bubble=[160, 400, 600, 855])
        assert render_area(a, [a, b]) == (200, 450, 300, 500)

    @pytest.mark.parametrize("kwargs", [dict(cls="text_free"), dict(angle=20), dict(bubble=None)])
    def test_free_rotated_or_bubbleless_text_keeps_the_box(self, kwargs):
        args = {"bubble": [160, 400, 600, 855], **kwargs}
        blk = block([275, 524, 484, 665], **args)
        assert render_area(blk, [blk]) == (275, 524, 484, 665)

    def test_a_box_larger_than_the_inscribed_rectangle_is_kept(self):
        blk = block([110, 110, 390, 290], bubble=[100, 100, 400, 300])
        assert render_area(blk, [blk]) == (110, 110, 390, 290)


class TestPlacement:
    def test_the_text_is_centred_in_its_area(self):
        assert place_in_area((100, 200, 300, 400), 100, 50, Alignment.Center) == (150, 275)

    def test_left_and_right_alignment_keep_their_side(self):
        assert place_in_area((100, 200, 300, 400), 100, 50, Alignment.Left) == (100, 275)
        assert place_in_area((100, 200, 300, 400), 100, 50, Alignment.Right) == (200, 275)

    def test_rotated_text_keeps_the_corner_its_rotation_assumes(self):
        blk = block([10, 20, 110, 70], angle=30)
        assert text_position(blk, (0, 0, 500, 500), 50, 20, Alignment.Center) == (10, 20)
