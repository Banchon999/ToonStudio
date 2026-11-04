"""The translation prompt says which instruction wins when two disagree.

They do: the Manhwa and Webtoon presets ask for modern, casual Thai while a
martial-arts series' setting asks for ข้า…ขอรับ, and "sound natural" pulls
against a glossary term. NovelTrans found a stated order the cheapest fix
for a model settling each clash differently from page to page.
"""

from modules.utils.prompts import RULE_PRIORITY_HEADER, PromptManager, rule_priority


def _ranks(block):
    return [line.split(". ", 1)[1] for line in block.splitlines()[1:]]


def test_glossary_outranks_the_speaker_map_which_outranks_style():
    ranks = _ranks(rule_priority("Thai", "historical"))
    order = [next(i for i, r in enumerate(ranks) if r.startswith(word))
             for word in ("The output format", "The glossary", "The speaker map", "The series setting",
                          "The speech particle rules", "The translation style", "The extra context")]
    assert order == sorted(order) and len(ranks) == 7


def test_only_rules_the_prompt_contains_are_ranked():
    auto = rule_priority("Thai", "auto")
    assert "series setting" not in auto and "speaker map" in auto
    english = rule_priority("English", "historical")
    assert "speaker map" not in english and "particle" not in english
    assert _ranks(english)[0].endswith("written in English.")


def test_the_priority_is_the_last_rule_in_every_system_prompt(tmp_path):
    manager = PromptManager(str(tmp_path / "prompts.json"))
    for preset in ("Default", "Manhwa", "Webtoon"):
        manager.active_preset = preset
        for target in ("Thai", "English"):
            prompt = manager.build_system_prompt("Korean", target, "historical")
            tail = prompt.split(RULE_PRIORITY_HEADER, 1)[1]
            assert prompt.count(RULE_PRIORITY_HEADER) == 1
            assert "SPEECH PARTICLE RULES" not in tail and "OUTPUT FORMAT" not in tail
