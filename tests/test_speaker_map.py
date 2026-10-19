"""Deciding who speaks each bubble before translating into Thai.

Measured on a three-page conversation (Korean, Chinese, English) with the
same model: identifying the speaker inside the translation request gave 9%
of Korean bubbles the wrong ครับ/ค่ะ even where the bubble's tail points at a
clearly drawn woman — the model credited a bubble to the name inside it. A
request that asked only who speaks got every one of those right. These tests
pin the parts that do not need a model.
"""

import types

import numpy as np
import pytest

from modules.translation.llm.base import BaseLLMTranslation
from modules.utils.speaker_map import (
    Character,
    Speaker,
    apply_speaker_map,
    build_speaker_prompt,
    fix_particles,
    parse_speaker_reply,
    speaker_map_block,
)
from modules.utils.textblock import TextBlock

CHARS = [Character("서미나", "มินา", "female"), Character("미나", "มินา", "female"),
         Character("강준", "จุน", "male")]


def block(text, translation=""):
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]), text=text)
    blk.translation = translation
    return blk


class TestPrompt:
    def test_it_asks_only_who_speaks_with_the_glossary_genders(self):
        p = build_speaker_prompt("Korean", ["죄송해요, 엄마.", "됐다."], CHARS[:1])
        assert "Do not translate" in p
        assert "- 서미나 = มินา (female)" in p
        assert "1. 죄송해요, 엄마." in p and "2. 됐다." in p
        assert "exactly 2 items" in p
        assert "spoken TO" in p

    def test_gender_words_follow_the_source_language(self):
        assert "누나" in build_speaker_prompt("Korean", ["x"], [])
        assert "talked ABOUT" in build_speaker_prompt("Korean", ["x"], [])
        assert "누나" not in build_speaker_prompt("Chinese", ["x"], [])
        assert "本小姐" in build_speaker_prompt("Chinese", ["x"], [])
        assert "sir, ma'am" in build_speaker_prompt("English", ["x"], [])

    def test_no_characters_is_said_so(self):
        assert "(none)" in build_speaker_prompt("English", ["x"], [])


class TestReply:
    def test_reads_the_blocks_and_lets_the_glossary_gender_win(self):
        raw = ('```json\n{"blocks":[{"q":1,"speaker":"미나","gender":"male"},'
               '{"q":2,"speaker":"Mina\'s mother","gender":"female"},'
               '{"q":3,"speaker":"narration","gender":"female"}]}\n```')
        got = parse_speaker_reply(raw, 3, CHARS)
        assert [s.gender for s in got] == ["female", "female", "unknown"]
        assert got[0].name == "미나"

    def test_a_reply_as_a_bare_array_is_read_too(self):
        got = parse_speaker_reply('[{"q":1,"speaker":"강준","gender":"unknown"}]', 1, CHARS)
        assert got[0].gender == "male"   # the glossary knows

    def test_missing_items_are_unknown_and_garbage_is_none(self):
        got = parse_speaker_reply('{"blocks":[{"q":2,"speaker":"x","gender":"female"}]}', 3, [])
        assert [s.gender for s in got] == ["unknown", "female", "unknown"]
        assert parse_speaker_reply("sorry, I can't", 2, []) is None

    def test_a_longer_name_wins_over_a_shorter_one_inside_it(self):
        chars = [Character("철수", "ชอลซู", "male"), Character("김철수의 누나", "พี่สาว", "female")]
        got = parse_speaker_reply('{"blocks":[{"q":1,"speaker":"김철수의 누나","gender":"unknown"}]}', 1, chars)
        assert got[0].gender == "female"


class TestMapBlock:
    def test_it_names_the_particle_per_block_without_repeating_the_source(self):
        text = speaker_map_block([Speaker("Mina", "female"), Speaker("guard", "male"), Speaker("", "unknown")])
        assert "block_0: Mina (female → ค่ะ/คะ" in text
        assert "block_1: guard (male → ครับ" in text
        assert "block_2: unknown (speaker's gender unknown → no ครับ/ค่ะ)" in text

    def test_nothing_known_sends_nothing(self):
        assert speaker_map_block([Speaker("?", "unknown")]) == ""
        assert speaker_map_block(None) == ""


class TestFixParticles:
    @pytest.mark.parametrize("text, gender, want", [
        ("ขอโทษครับแม่ จุนอยู่ที่ตลาดครับ", "female", "ขอโทษค่ะแม่ จุนอยู่ที่ตลาดค่ะ"),
        ("ไปไหนครับ?", "female", "ไปไหนคะ?"),
        ("ผมจะไปนะครับ", "female", "ฉันจะไปนะคะ"),
        ("ผมยาวมากครับ", "female", "ผมยาวมากค่ะ"),           # hair stays hair
        ("ดิฉันเข้าใจแล้วค่ะ", "male", "ผมเข้าใจแล้วครับ"),
        ("ได้คะแนนดีค่ะ", "male", "ได้คะแนนดีครับ"),          # คะแนน is not คะ
        ("กระหม่อมเข้าใจพ่ะย่ะค่ะ", "male", "กระหม่อมเข้าใจพ่ะย่ะค่ะ"),
        ("หิวจะแย่แล้ว", "female", "หิวจะแย่แล้ว"),            # no particle is left alone
        ("ขอบคุณครับ", "unknown", "ขอบคุณครับ"),
        ("ไปแล้วค่ะ/ครับ ขอบคุณค่ะ/ครับ", "unknown", "ไปแล้ว ขอบคุณ"),   # a hedge is never final text
        ("ไปแล้วครับ/ค่ะ", "female", "ไปแล้วค่ะ"),
        ("ไปไหนคะ / ครับ", "male", "ไปไหนครับ"),
    ])
    def test_swaps_only_what_contradicts_the_gender(self, text, gender, want):
        assert fix_particles(text, gender) == want

    def test_apply_puts_the_map_on_the_blocks_and_counts_fixes(self):
        blocks = [block("a", "ขอบคุณครับ"), block("b", "ได้ครับ"), block("c", "ค่ะ")]
        for b in blocks:
            b.speaker, b.speaker_gender = "จุน", "male"
        changed = apply_speaker_map(blocks, [Speaker("Mina", "female"), Speaker("", "unknown"),
                                             Speaker("guard", "male")])
        assert changed == 2
        assert (blocks[0].translation, blocks[0].speaker, blocks[0].speaker_gender) == ("ขอบคุณค่ะ", "Mina", "female")
        assert (blocks[1].translation, blocks[1].speaker_gender) == ("ได้ครับ", "male")   # map unknown: untouched
        assert blocks[2].translation == "ครับ"


class FakeEngine(BaseLLMTranslation):
    """Records both requests; answers the speaker one, then the translation."""

    def __init__(self, speaker_reply, translation_reply):
        super().__init__()
        self.replies = [speaker_reply, translation_reply]
        self.calls = []
        self.image_seen = []
        self.source_lang, self.target_lang = "Korean", "Thai"
        self.temperature = 1.0

    def get_system_prompt(self, source_lang, target_lang):
        return "SYSTEM"

    def _perform_translation(self, user_prompt, system_prompt, image):
        self.calls.append((user_prompt, system_prompt, self.temperature))
        self.image_seen.append(self.img_as_llm_input)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class TestEngine:
    SPEAKERS = '{"blocks":[{"q":1,"speaker":"엄마","gender":"female"},{"q":2,"speaker":"미나","gender":"unknown"}]}'
    TRANSLATION = ('{"block_0": {"speaker": "แม่", "gender": "female", "translation": "ไปไหนมา"},'
                   ' "block_1": {"speaker": "จุน", "gender": "male", "translation": "ขอโทษครับแม่"}}')

    def test_speakers_are_asked_first_at_temperature_zero_and_then_followed(self):
        engine = FakeEngine(self.SPEAKERS, self.TRANSLATION)
        engine.speaker_characters = CHARS
        blocks = [block("미나야, 어디 갔다 왔니?"), block("죄송해요, 엄마. 준이 시장에 있었어요.")]
        engine.translate(blocks, np.zeros((8, 8, 3), np.uint8), "GLOSSARY")
        (speaker_prompt, speaker_system, temp), (user_prompt, system, temp2) = engine.calls
        assert "Do not translate" in speaker_prompt and temp == 0
        assert "- 미나 = มินา (female)" in speaker_prompt   # the given name is on the page
        assert temp2 == 1.0                                   # restored for the translation
        assert "SPEAKER MAP" in user_prompt and "block_1: 미나 (female" in user_prompt
        assert user_prompt.index("GLOSSARY") < user_prompt.index("SPEAKER MAP") < user_prompt.index("Translate this")
        assert blocks[1].translation == "ขอโทษค่ะแม่"
        assert blocks[1].speaker_gender == "female"

    def test_the_speaker_request_sees_the_page_even_with_image_input_off(self):
        # Image input is off by default; in a real run the speaker step then
        # never saw the woman the bubble pointed at and gave her line to Jun.
        engine = FakeEngine(self.SPEAKERS, self.TRANSLATION)
        engine.img_as_llm_input = False
        engine.translate([block("a"), block("b")], np.zeros((8, 8, 3), np.uint8), "")
        assert engine.image_seen == [True, False]     # speakers with it, translation as set
        assert engine.img_as_llm_input is False

    def test_a_failed_speaker_request_still_translates(self):
        engine = FakeEngine(RuntimeError("rate limited"), self.TRANSLATION)
        blocks = [block("a"), block("b")]
        engine.translate(blocks, None, "")
        assert blocks[1].translation == "ขอโทษครับแม่"
        assert "SPEAKER MAP" not in engine.calls[-1][0]
        assert engine.temperature == 1.0

    def test_other_target_languages_make_one_request(self):
        engine = FakeEngine('{"block_0": "hello", "block_1": "bye"}', "")
        engine.target_lang = "English"
        engine.translate([block("a"), block("b")], None, "")
        assert len(engine.calls) == 1


def test_translator_hands_the_engine_glossary_characters_under_every_name(tmp_path):
    from modules.translation.processor import Translator
    from modules.utils.glossary import GlossaryEntry, GlossaryManager

    manager = GlossaryManager(str(tmp_path))
    manager.save = lambda: None
    manager.enabled = True
    manager.entries = [GlossaryEntry("서미나", "มินา", "character", "female"),
                       GlossaryEntry("강준", "จุน", "character", "male", aliases=["준이=จุน"]),
                       GlossaryEntry("마나석", "หินมานา", "item")]
    translator = Translator.__new__(Translator)
    translator.settings = types.SimpleNamespace(ui=types.SimpleNamespace(
        glossary_page=types.SimpleNamespace(manager=manager)))
    forms = {(c.source, c.gender) for c in translator._speaker_characters()}
    assert {("서미나", "female"), ("미나", "female"), ("강준", "male"), ("준이", "male")} <= forms
    assert not any(s == "마나석" for s, _ in forms)
    manager.enabled = False
    assert translator._speaker_characters() == []
