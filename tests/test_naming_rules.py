"""Glossary extraction gets the naming conventions of the language it reads.

One prompt for every language put Chinese names right 2–3 times in 7 in
NovelTrans; each language's own conventions took it to 6–7 in 7.
"""

import json
import types

from modules.utils.naming_rules import (
    JUNK_RULES, extraction_naming_rules, rules_language, script_language,
)


def test_each_source_gets_its_own_rules_and_no_other():
    korean = extraction_naming_rules("Korean", "Thai")
    chinese = extraction_naming_rules("Chinese", "Thai")
    assert "최 ชเว" in korean and "화산 ฮวาซาน" in korean
    assert "หลิน" in chinese and "ศิษย์พี่" in chinese
    assert "최" not in chinese and "林" not in korean
    assert JUNK_RULES in korean and JUNK_RULES in chinese


def test_other_targets_get_the_generic_rule_in_their_language():
    rules = extraction_naming_rules("Korean", "English")
    assert "English publisher" in rules and "ชเว" not in rules


def test_the_letters_say_which_language_a_text_is():
    assert script_language("성진우가 게이트 앞에 섰다. 헌터 협회에서 연락이 왔다.") == "Korean"
    assert script_language("林凡站在青云宗的山门前，师兄看着他。长老来了。") == "Chinese"
    assert script_language("田中さんは学校へ行きました。先輩が待っている。とても強い。") == "Japanese"
    assert script_language("The duke rode into the capital with his knights at dawn.") == "English"
    assert script_language("!!! ...") is None


def test_the_text_wins_over_a_wrong_or_auto_setting():
    korean = "성진우가 게이트 앞에 섰다. 헌터 협회에서 연락이 왔다. 마나가 넘쳤다."
    assert rules_language("Chinese", korean) == ("Korean", "Korean")   # warn: setting disagrees
    assert rules_language("Auto", korean) == ("Korean", None)          # nothing set, nothing to warn
    assert rules_language("Korean", korean) == ("Korean", None)


def test_the_extraction_prompt_carries_the_rules_of_the_texts_language(monkeypatch):
    from modules.translation.base import LLMTranslation
    import modules.translation.processor as processor
    from modules.utils import glossary_extractor as gx

    prompts = []

    class Engine(LLMTranslation):
        def initialize(self, *a, **k):
            pass

        def translate(self, *a, **k):
            return {}

        def _perform_translation(self, user_prompt, system_prompt, image):
            prompts.append(system_prompt)
            return json.dumps([])

    class FakeTranslator:
        def __init__(self, *a, **k):
            self.engine = Engine()
            self.source_lang_en, self.target_lang_en = "Chinese", "Thai"   # the wrong series is open

    monkeypatch.setattr(processor, "Translator", FakeTranslator)
    combo = types.SimpleNamespace(currentText=lambda: "x")
    main = types.SimpleNamespace(s_combo=combo, t_combo=combo)
    gx.extract_glossary_terms(main, "성진우가 게이트 앞에 섰다. 헌터 협회에서 연락이 왔다.\n" * 3, set())
    assert "Korean → Thai" in prompts[0] and "Chinese → Thai" not in prompts[0]
    assert "series in Korean" in prompts[0]
