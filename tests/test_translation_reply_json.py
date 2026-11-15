"""A model's translation reply that is not quite JSON.

Reported from the 3.4.3 test build as a traceback dialog —
"JSONDecodeError: Expecting ',' delimiter: line 6 column 126" from
`set_texts_from_json` — which stopped the whole multi-page Translate. The
reply was read with a bare `json.loads`; models quote speech inside a Thai
translation without escaping it, drop a comma between fields, leave a
trailing comma, wrap the object in a code fence or add a remark after it.

`parse_reply_json` reads the object as written, then mended, then block by
block; a reply it still cannot read is asked for once more, and a second
failure is an `APIError` of kind `bad_reply` — a sentence, not a traceback.
"""

import json

import pytest

from core.messages import api_error_text
from modules.translation.llm.base import BaseLLMTranslation
from modules.utils.api_errors import APIError, BAD_REPLY
from modules.utils.textblock import TextBlock
from modules.utils.translator_utils import ReplyParseError, parse_reply_json, set_texts_from_json


class TestReading:
    def test_valid_json_reads_exactly_as_json_loads_does(self):
        reply = json.dumps({"block_0": {"speaker": "จุน", "gender": "male", "translation": "ไปกัน"},
                            "block_1": "ครับ"}, ensure_ascii=False, indent=4)
        assert parse_reply_json(reply) == json.loads(reply)

    def test_a_quote_inside_a_translation(self):
        reply = ('{\n  "block_0": {\n    "speaker": "มินา",\n    "gender": "female",\n'
                 '    "translation": "เขาบอกว่า "ไปกันเถอะ" แล้วก็เดินออกไปเลยค่ะ"\n  },\n'
                 '  "block_1": "โอเค"\n}')
        with pytest.raises(json.JSONDecodeError, match="Expecting ',' delimiter"):
            json.loads(reply)   # the reported error
        value = parse_reply_json(reply)
        assert value["block_0"]["translation"] == 'เขาบอกว่า "ไปกันเถอะ" แล้วก็เดินออกไปเลยค่ะ'
        assert value["block_0"]["gender"] == "female" and value["block_1"] == "โอเค"

    def test_a_missing_comma_between_fields(self):
        reply = ('{\n  "block_0": {\n    "speaker": "จุน"\n    "gender": "male",\n'
                 '    "translation": "ไปกัน"\n  }\n  "block_1": "ครับ"\n}')
        with pytest.raises(json.JSONDecodeError, match="Expecting ',' delimiter"):
            json.loads(reply)
        assert parse_reply_json(reply) == {
            "block_0": {"speaker": "จุน", "gender": "male", "translation": "ไปกัน"}, "block_1": "ครับ"}

    def test_a_fence_a_trailing_comma_and_a_remark_with_braces(self):
        reply = '```json\n{"block_0": "ก", "block_1": "ข",}\n```\nNote: {done}'
        assert parse_reply_json(reply) == {"block_0": "ก", "block_1": "ข"}

    def test_a_raw_line_break_inside_a_translation(self):
        assert parse_reply_json('{"block_0": "บรรทัดแรก\nบรรทัดสอง"}') == {"block_0": "บรรทัดแรก\nบรรทัดสอง"}

    def test_what_cannot_be_mended_is_read_block_by_block(self):
        # A quote followed by a comma looks like the end of the string; the
        # whole object stays broken, but every block is still recovered.
        reply = ('{"block_0": {"speaker": "A", "gender": "male", "translation": "เขาพูดว่า "ไป", แล้วเดิน"},'
                 ' "block_1": "ต่อ"}')
        value = parse_reply_json(reply)
        assert value["block_0"]["translation"] == 'เขาพูดว่า "ไป", แล้วเดิน'
        assert value["block_1"] == "ต่อ"

    def test_no_translation_at_all_is_an_error_not_an_empty_page(self):
        with pytest.raises(ReplyParseError):
            parse_reply_json("Sorry, I can't help with that.")
        with pytest.raises(ReplyParseError):
            set_texts_from_json([TextBlock()], "Sorry, I can't help with that.")


class _Model(BaseLLMTranslation):
    """Answers with the replies it is given, in turn."""

    PROVIDER = "OpenRouter"

    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.calls = 0
        self.model = "google/gemini-3.1-flash-lite"
        self.source_lang, self.target_lang = "English", "English"

    def get_system_prompt(self, source_lang, target_lang):
        return ""

    def identify_speakers(self, blk_list, image):
        return None

    def _perform_translation(self, user_prompt, system_prompt, image):
        self.calls += 1
        return self.replies.pop(0)


def _blocks():
    blocks = [TextBlock(), TextBlock()]
    for blk, text in zip(blocks, ("GO", "OK")):
        blk.text = text
    return blocks


class TestAskingAgain:
    def test_a_repairable_reply_is_not_asked_for_twice(self):
        model = _Model(['{"block_0": "ไป", "block_1": "โอเค",}'])
        blocks = model.translate(_blocks(), None, "")
        assert model.calls == 1
        assert [b.translation for b in blocks] == ["ไป", "โอเค"]

    def test_an_unreadable_reply_is_asked_for_once_more(self):
        model = _Model(["I cannot do JSON today.", '{"block_0": "ไป", "block_1": "โอเค"}'])
        blocks = model.translate(_blocks(), None, "")
        assert model.calls == 2
        assert [b.translation for b in blocks] == ["ไป", "โอเค"]

    def test_two_unreadable_replies_say_what_to_do(self):
        model = _Model(["no", "still no"])
        with pytest.raises(APIError) as caught:
            model.translate(_blocks(), None, "")
        assert caught.value.kind == BAD_REPLY
        text = api_error_text(caught.value)
        assert "google/gemini-3.1-flash-lite" in text and "Translate again" in text
        assert "Traceback" not in text
