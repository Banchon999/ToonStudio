"""A series is set in the present day or in the past, and its Thai follows.

A modern webtoon speaks ผม…ครับ and a martial-arts one ข้า…ขอรับ. With the
setting unknown the rules offered both, and NovelTrans found a model given
both picks both — a page of ข้า with ครับ on the end. The setting belongs to
the series, so it is stored with the glossary profile.
"""

import json
import types

import pytest

from modules.translation.llm.base import BaseLLMTranslation
from modules.utils import thai_speech
from modules.utils.glossary import GlossaryEntry, GlossaryManager
from modules.utils.speaker_map import Speaker, fix_particles, speaker_map_block, strip_polite
from modules.utils.textblock import TextBlock


def block(text, translation="", gender=""):
    blk = TextBlock(text_bbox=[0, 0, 10, 10])
    blk.text, blk.translation, blk.speaker_gender = text, translation, gender
    return blk


def test_the_setting_is_stored_with_the_profile_and_only_when_set(tmp_path):
    manager = GlossaryManager(str(tmp_path))
    manager.entries = [GlossaryEntry("천마", "ปีศาจสวรรค์", "character", "male")]
    manager.save()
    assert "setting" not in json.loads(open(manager.file_path, encoding="utf-8").read())

    manager.set_setting("historical")
    assert json.loads(open(manager.file_path, encoding="utf-8").read())["setting"] == "historical"
    assert GlossaryManager(str(tmp_path)).setting == "historical"

    manager.create_profile("Hunter Academy")
    assert manager.setting == "auto"
    manager.switch_profile("Default")
    assert manager.setting == "historical"
    manager.set_setting("nonsense")
    assert manager.setting == "auto"


def test_a_characters_pronouns_follow_the_setting(tmp_path):
    manager = GlossaryManager(str(tmp_path))
    manager.save = lambda: None
    manager.match_only = False
    manager.entries = [GlossaryEntry("소연", "โซยอน", "character", "female"),
                       GlossaryEntry("진우", "จินอู", "character", "male")]
    manager.setting = "historical"
    old = manager.build_prompt()
    assert "particle→เจ้าค่ะ/เจ้าคะ" in old and "particle→ขอรับ" in old
    assert "ครับ" not in old and "ผม" not in old and "ดิฉัน" not in old
    manager.setting = "modern"
    new = manager.build_prompt()
    assert "1st→ผม" in new and "particle→ครับ" in new and "ข้า" not in new and "ขอรับ" not in new


def test_the_rules_ask_for_one_register():
    auto = thai_speech.speech_particle_rules("Korean")
    historical = thai_speech.speech_particle_rules("Korean", "historical")
    modern = thai_speech.speech_particle_rules("Korean", "modern")
    assert "SETTING:" not in auto
    assert "SETTING: HISTORICAL" in historical and "Male speaker: ขอรับ" in historical
    assert "Male speaker: ครับ / นะครับ" not in historical
    assert "SETTING: PRESENT DAY" in modern and "ขอรับ" not in modern.split("NEVER")[0]


def test_a_changed_setting_changes_the_context_the_cache_is_keyed_on(tmp_path):
    from app.ui.settings.settings_page import SettingsPage

    manager = GlossaryManager(str(tmp_path))
    manager.save = lambda: None
    page = types.SimpleNamespace(ui=types.SimpleNamespace(
        extra_context=types.SimpleNamespace(toPlainText=lambda: "A wuxia story."),
        glossary_page=types.SimpleNamespace(manager=manager)))
    assert SettingsPage.get_extra_context(page, "x") == "A wuxia story."
    manager.setting = "historical"
    assert SettingsPage.get_extra_context(page, "x").startswith("A wuxia story.\n\nSeries setting: historical")


class Engine(BaseLLMTranslation):
    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.calls = []
        self.source_lang, self.target_lang = "Korean", "Thai"

    def _perform_translation(self, user_prompt, system_prompt, image):
        self.calls.append((user_prompt, system_prompt))
        return self.replies.pop(0)


def test_a_historical_series_is_translated_and_fixed_in_its_own_register():
    speakers = '{"blocks":[{"q":1,"speaker":"소연","gender":"female"},{"q":2,"speaker":"진우","gender":"male","mode":"thought"}]}'
    translation = '{"block_0": "ผมไม่ไปครับ", "block_1": "ผมต้องไปครับ"}'
    engine = Engine([speakers, translation])
    engine.series_setting = "historical"
    blocks = [block("나는 안 가요"), block("가야 해")]
    engine.translate(blocks, None, "")
    user_prompt, system_prompt = engine.calls[1]
    assert "SETTING: HISTORICAL" in system_prompt
    assert "it is เจ้าค่ะ/เจ้าคะ" in user_prompt and "self ข้า" in user_prompt
    assert [b.translation for b in blocks] == ["ข้าไม่ไปเจ้าค่ะ", "ข้าต้องไป"]


@pytest.mark.parametrize("text, gender, setting, fixed", [
    ("ผมไม่รู้ครับ", "female", "auto", "ฉันไม่รู้ค่ะ"),          # unchanged behaviour
    ("ผมไม่รู้ครับ", "female", "historical", "ข้าไม่รู้เจ้าค่ะ"),
    ("ไปไหนครับ?", "female", "historical", "ไปไหนเจ้าคะ?"),
    ("ดิฉันไปค่ะ", "male", "historical", "ข้าไปขอรับ"),
    ("ไปไหนเจ้าคะ", "male", "auto", "ไปไหนขอรับ"),              # not "เจ้าครับ"
    ("ได้ขอรับ", "female", "modern", "ได้ค่ะ"),
    ("ได้เจ้าค่ะ", "male", "modern", "ได้ครับ"),
])
def test_a_wrong_gender_word_becomes_the_settings_form(text, gender, setting, fixed):
    assert fix_particles(text, gender, setting) == fixed


def test_a_thought_in_a_historical_series_thinks_in_khaa():
    assert strip_polite("ข้าน้อยต้องไปขอรับ", "historical") == "ข้าต้องไป"
    assert strip_polite("ผมต้องไปครับ") == "ฉันต้องไป"
    text = speaker_map_block([Speaker("진우", "male", mode="thought")], "historical")
    assert "self ข้า" in text and "never ข้าน้อย/ผม/ดิฉัน" in text


@pytest.mark.parametrize("translation, setting, reason", [
    ("ไปกันเถอะครับ", "historical", thai_speech.MODERN_IN_HISTORICAL),
    ("ดิฉันไม่ทราบ", "historical", thai_speech.MODERN_IN_HISTORICAL),
    ("ไปกันเถอะเจ้าค่ะ", "historical", None),
    ("ขอบพระทัยพ่ะย่ะค่ะ", "historical", None),       # royal register ends in ค่ะ
    ("ได้คะแนนเต็ม", "historical", None),             # คะแนน is not คะ
    ("รับทราบขอรับ", "modern", thai_speech.ARCHAIC_IN_MODERN),
    ("ข้าวอร่อยมาก", "modern", None),                 # ข้าว is not ข้า
    ("ไปกันเถอะครับ", "auto", None),
])
def test_a_line_in_the_other_register_is_reported(translation, setting, reason):
    issues = thai_speech.check_speech([block("x", translation)], setting)
    assert [i.reason for i in issues] == ([reason] if reason else [])


def test_the_translator_hands_the_profiles_setting_to_the_engine(tmp_path):
    from modules.translation.processor import Translator

    manager = GlossaryManager(str(tmp_path))
    manager.save = lambda: None
    translator = Translator.__new__(Translator)
    translator.settings = types.SimpleNamespace(ui=types.SimpleNamespace(
        glossary_page=types.SimpleNamespace(manager=manager)))
    assert translator._series_setting() == "auto"
    manager.setting = "historical"
    assert translator._series_setting() == "historical"
    translator.settings = types.SimpleNamespace(ui=types.SimpleNamespace())
    assert translator._series_setting() == "auto"


def test_the_glossary_page_sets_and_shows_the_profiles_setting(qapp):
    from app.ui.settings.glossary_page import GlossaryPage

    page = GlossaryPage()
    saved = []
    page.manager.save = lambda: saved.append(page.manager.setting)
    try:
        page.setting_combo.setCurrentIndex(thai_speech.SETTINGS.index("historical"))
        assert page.manager.setting == "historical" and saved == ["historical"]
        page.manager.setting = "modern"
        page._refresh_setting()
        assert page.setting_combo.currentIndex() == thai_speech.SETTINGS.index("modern")
    finally:
        page.deleteLater()
