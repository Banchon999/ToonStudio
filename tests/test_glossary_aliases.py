"""Short names and homographs in the glossary.

Found by translating a four-page Korean conversation page by page:

- A character introduced as 한도윤 is called "도윤아" on a later page. Nothing
  on that page matched the glossary, so nothing was sent, and the name came
  out as โดอุน, โดวุน, โดวอน or โดมิน — right in 3 of 11 runs.
- 철수 is a man's name and the word "withdraw". A page ordering a retreat got
  the name sent with "translate exactly as given"; one run in seven wrote
  "ทุกคนชอลซู!", and the check afterwards warned on the six runs that had
  translated it correctly and not on the one that had not. Telling the model
  in the prompt to apply a term only where it means that, with or without
  asking it to mark such blocks, measured no better (2-10 runs in 16 wrote
  the name), so the name is now held back before the prompt is built.
"""

import csv
import json

import numpy as np
import pytest

from modules.utils.glossary import (
    GlossaryEntry,
    GlossaryManager,
    korean_given_name,
    parse_aliases,
)
from modules.utils.textblock import TextBlock


@pytest.fixture
def manager(tmp_path):
    m = GlossaryManager(str(tmp_path))
    m.save = lambda: None
    m.enabled = True
    m.match_only = True
    m.entries = [
        GlossaryEntry("김철수", "คิมชอลซู", "character", "male"),
        GlossaryEntry("철수", "ชอลซู", "character", "male"),
        GlossaryEntry("이서연", "อีซอยอน", "character", "female"),
        GlossaryEntry("한도윤", "โดยุน ฮัน", "character", "male"),
        GlossaryEntry("그림자 군주", "ราชันเงา", "title"),
    ]
    return m


def sent(manager, text):
    return {(m.entry.source, m.alias_of.source if m.alias_of else None) for m in manager.find_matches(text)}


def block(text, translation=""):
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]), text=text)
    blk.translation = translation
    return blk


class TestGivenNames:
    def test_a_korean_full_name_has_a_given_name(self):
        assert korean_given_name("한도윤") == "도윤"
        assert korean_given_name("남궁민수") == "민수"
        assert korean_given_name("민준") == ""            # no family name to drop
        assert korean_given_name("김준") == ""            # a one-syllable given name matches too much
        assert korean_given_name("Kael Voss") == ""

    def test_a_given_name_alone_reaches_the_prompt(self, manager):
        assert sent(manager, "도윤아, 정신 차려!") == {("도윤", "한도윤")}
        assert sent(manager, "서연 씨, 마나석을 줘.") == {("서연", "이서연")}

    def test_it_is_not_sent_again_inside_the_full_name(self, manager):
        assert sent(manager, "한도윤 씨가 왔어") == {("한도윤", None)}

    def test_it_must_start_a_word(self, manager):
        # What OCR makes of "협회에서 연락": 서연 inside 에서연락 is no name.
        assert ("서연", "이서연") not in sent(manager, "협회에서연락 왔어요")
        assert ("서연", "이서연") not in sent(manager, "협회에서 연락 왔어요")

    def test_a_glossary_term_wins_over_a_derived_given_name(self, manager):
        # 철수 is its own entry, so 김철수's given name is that entry, not an alias.
        assert sent(manager, "철수야!!") == {("철수", None)}

    def test_two_characters_with_one_given_name_get_neither(self, manager):
        manager.entries += [GlossaryEntry("박민준", "พัคมินจุน", "character"),
                            GlossaryEntry("최민준", "ชเวมินจุน", "character")]
        assert not any(a for _, a in sent(manager, "민준아 밥 먹자"))

    def test_only_characters_get_a_given_name(self, manager):
        manager.entries.append(GlossaryEntry("백호검", "ดาบพยัคฆ์ขาว", "item"))
        assert sent(manager, "호검아") == set()

    def test_the_prompt_asks_for_the_same_given_name(self, manager):
        prompt = manager.build_prompt("도윤아, 정신 차려!")
        line = next(ln for ln in prompt.splitlines() if ln.startswith("- 도윤"))
        assert "โดยุน ฮัน" in line and "한도윤" in line and "only that part" in line and "script" in line
        assert "ครับ" in line   # the character's gender still travels


class TestListedAliases:
    def test_an_alias_with_its_own_translation(self, manager):
        manager.entries[3].aliases = ["도윤이=โดยุน"]
        prompt = manager.build_prompt("도윤이 어디 갔어?")
        assert "- 도윤이 => โดยุน (short for 한도윤 => โดยุน ฮัน)" in prompt

    def test_aliases_parse_from_a_cell_and_survive_save_and_csv(self, manager, tmp_path):
        assert parse_aliases("도윤, 도윤이=โดยุน; 윤이") == ["도윤", "도윤이=โดยุน", "윤이"]
        entry = GlossaryEntry.from_dict({"source": "한도윤", "target": "โดยุน ฮัน", "aliases": "도윤이=โดยุน, 한도윤"})
        assert entry.aliases == ["도윤이=โดยุน"]    # the name itself is not its own alias
        manager.entries = [entry]
        path = tmp_path / "g.csv"
        manager.export_csv(str(path))
        assert list(csv.reader(open(path, encoding="utf-8-sig")))[1][-1] == "도윤이=โดยุน"
        manager.entries = []
        manager.import_csv(str(path))
        assert manager.entries[0].aliases == ["도윤이=โดยุน"]

    def test_a_glossary_saved_before_aliases_still_loads(self, tmp_path):
        m = GlossaryManager(str(tmp_path))
        with open(m.file_path, "w", encoding="utf-8") as f:
            json.dump({"entries": [{"source": "김철수", "target": "คิมชอลซู", "type": "character"}]}, f)
        m.load()
        assert m.entries[0].aliases == []


class TestCheckingShortNames:
    def test_any_word_of_a_spaced_full_translation_counts(self, manager):
        blocks = [block("도윤아, 정신 차려!", "โดยุน ตั้งสติหน่อย!")]
        assert manager.check_translation(blocks) == []
        blocks = [block("도윤아, 정신 차려!", "โดมิน ตั้งสติหน่อย!")]
        assert [i.source_term for i in manager.check_translation(blocks)] == ["도윤"]

    def test_a_one_word_full_translation_cannot_be_checked_for_a_given_name(self, manager):
        # Which part of อีซอยอน is 서연 is not recorded, so no guess is made.
        assert manager.check_translation([block("서연 씨!", "คุณซอยอน!")]) == []


class TestHomographs:
    PAGE = ["그 사람 또 왔어?", "본부에서 철수하라는 명령이 내려왔어!", "지금 당장?", "전원 철수!"]

    def test_a_name_used_only_as_a_verb_on_the_page_is_not_sent(self, manager):
        text = "\u2029".join(self.PAGE)
        assert ("철수", None) not in sent(manager, text)
        report = {m.entry.source: m for m in manager.match_report(text)}
        assert report["철수"].ordinary_word == "철수하라는"
        assert "철수" not in manager.build_prompt(text)

    def test_a_held_back_word_is_not_taken_over_by_a_fuzzy_name(self, manager):
        # Local OCR wrote "전원철수"; "원철수" is one letter from 김철수.
        page = "본부에서 철수하라는 명령이 내려왔어!\u2029전원철수!"
        assert sent(manager, page) == set()

    def test_one_use_as_a_name_sends_it(self, manager):
        assert ("철수", None) in sent(manager, "철수야, 철수하자!")
        assert ("철수", None) in sent(manager, "철수 씨, 전원 철수래요")

    def test_a_bare_use_decides_nothing(self, manager):
        assert ("철수", None) in sent(manager, "전원 철수!")
        assert ("철수", None) in sent(manager, "철수가 왔어")

    def test_with_and_to_are_particles_not_verbs(self, manager):
        assert ("철수", None) in sent(manager, "철수하고 같이 가")
        assert ("철수", None) in sent(manager, "철수한테 줘")

    def test_only_korean_characters_are_judged(self, manager):
        manager.entries.append(GlossaryEntry("회귀", "การย้อนเวลา", "term"))
        assert ("회귀", None) in sent(manager, "그는 회귀했다")

    def test_given_names_follow_the_same_rule(self, manager):
        manager.entries.append(GlossaryEntry("박진행", "พัคจินแฮง", "character"))
        assert ("진행", "박진행") not in sent(manager, "작전을 진행해!")
        assert ("진행", "박진행") in sent(manager, "진행아, 가자!")

    def test_the_check_does_not_report_the_word_translated_as_a_word(self, manager):
        translations = ["คนนั้นมาอีกแล้วเหรอ", "มีคำสั่งให้ถอนกำลัง!", "ตอนนี้เลยเหรอ", "ถอนกำลังทั้งหมด!"]
        blocks = [block(t, tr) for t, tr in zip(self.PAGE, translations)]
        assert manager.check_translation(blocks) == []


class TestGlossaryPage:
    @pytest.fixture
    def page(self, qapp):
        from app.ui.settings.glossary_page import GlossaryPage

        page = GlossaryPage()
        page.manager.save = lambda: None
        yield page
        page.deleteLater()

    def test_the_table_shows_listed_and_automatic_aliases(self, page):
        page.manager.entries = [
            GlossaryEntry("한도윤", "โดยุน ฮัน", "character", aliases=["도윤이=โดยุน"]),
            GlossaryEntry("마나석", "หินมานา", "item"),
        ]
        page.refresh_table()
        col = page.COLUMNS.index("aliases")
        cells = {page.table.item(r, 0).data(0x0100): page.table.item(r, col).text()
                 for r in range(page.table.rowCount())}
        assert "도윤이=โดยุน" in cells["한도윤"] and "도윤" in cells["한도윤"].replace("도윤이", "")
        assert cells["마나석"] == ""

    def test_the_entry_dialog_edits_aliases(self, page):
        from app.ui.settings.glossary_page import GlossaryEntryDialog

        dialog = GlossaryEntryDialog(["character"], GlossaryEntry("한도윤", "โดยุน ฮัน", "character",
                                                                 aliases=["도윤이"]), parent=page)
        assert dialog.aliases_input.text() == "도윤이"
        dialog.aliases_input.setText("도윤이, 윤이=ยุนอี")
        assert dialog.get_entry().aliases == ["도윤이", "윤이=ยุนอี"]
        dialog.deleteLater()

    def test_the_match_tester_names_the_full_name(self, page):
        from app.ui.settings.glossary_page import GlossaryMatchTestDialog

        page.manager.enabled = True
        page.manager.match_only = True
        page.manager.entries = [GlossaryEntry("한도윤", "โดยุน ฮัน", "character")]
        dialog = GlossaryMatchTestDialog(page.manager, "도윤아!", parent=page)
        assert "«한도윤»" in dialog.results.toPlainText()
        dialog.deleteLater()

    def test_the_match_tester_says_why_a_word_was_held_back(self, page):
        from app.ui.settings.glossary_page import GlossaryMatchTestDialog

        page.manager.enabled = True
        page.manager.entries = [GlossaryEntry("철수", "ชอลซู", "character")]
        dialog = GlossaryMatchTestDialog(page.manager, "전원 철수하라!", parent=page)
        assert "«철수하라»" in dialog.results.toPlainText()
        assert "철수" not in dialog.prompt_view.toPlainText()
        dialog.deleteLater()
