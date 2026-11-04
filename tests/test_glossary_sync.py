"""The team glossary merge, its AI referee and the Glossary page around them.

The merge rules are the owner's: a term both sides agree on is combined, a
term translated differently goes to the AI first, and nobody's edit is lost to
a sync. tests/test_glossary_sync_script.py runs the same code against the real
Apps Script; these pin the rules one at a time.
"""

import json
import os

import pytest

from modules.utils.glossary import GlossaryEntry, GlossaryManager
from modules.utils.glossary_sync import (
    Conflict, build_conflict_prompt, combine, load_base, parse_conflict_reply,
    plan_merge, reconcile_after_sync, save_base,
)


def E(source, target, **kw):
    return GlossaryEntry(source=source, target=target, **kw)


def by_key(entries):
    return {e.key: e for e in entries}


class TestPlanMerge:
    def test_first_sync_is_a_union(self):
        plan = plan_merge([E("마나", "มานา")], None, [E("길드", "กิลด์")])
        assert [plan.merged[k].target for k in plan.order] == ["มานา", "กิลด์"]
        assert (plan.pulled, plan.pushed, plan.conflicts) == (1, 1, [])

    def test_the_side_that_still_matches_the_base_gives_way(self):
        base = by_key([E("게이트", "เกต"), E("던전", "ดันเจี้ยน")])
        local = [E("게이트", "ประตูมิติ"), E("던전", "ดันเจี้ยน")]
        remote = [E("게이트", "เกต"), E("던전", "ดันเจียน")]
        plan = plan_merge(local, base, remote)
        assert plan.merged["게이트"].target == "ประตูมิติ"
        assert plan.merged["던전"].target == "ดันเจียน"
        assert (plan.pulled, plan.pushed) == (1, 1)

    def test_a_deletion_travels_only_over_an_unchanged_term(self):
        base = by_key([E("마나", "มานา"), E("포션", "โพชั่น")])
        plan = plan_merge([E("포션", "ยา")], base, [E("마나", "มานา")])
        # 마나: deleted here, untouched there → gone. 포션: deleted there, edited here → kept.
        assert set(plan.merged) == {"포션"}
        assert plan.deleted_there == 1

    def test_same_translation_is_combined_not_asked(self):
        plan = plan_merge(
            [E("한도윤", "ฮันโดยุน", type="character", aliases=["도윤"])], None,
            [E("한도윤", "ฮันโดยุน", type="character", gender="male", note="lead", aliases=["윤이", "도윤"])],
        )
        entry = plan.merged["한도윤"]
        assert (entry.gender, entry.note, entry.aliases) == ("male", "lead", ["도윤", "윤이"])
        assert plan.combined == 1 and not plan.conflicts

    def test_a_term_matched_by_key_not_spelling(self):
        # Composed and decomposed Hangul are one term (term_key), not two rows.
        decomposed = "한"  # 한 as jamo
        plan = plan_merge([E("한", "ฮัน")], None, [E(decomposed, "ฮัน")])
        assert len(plan.order) == 1

    def test_different_translation_is_a_translation_conflict(self):
        plan = plan_merge([E("차해인", "ชาแฮอิน")], None, [E("차해인", "ชาเฮอิน")])
        assert [(c.kind, c.local.target, c.remote.target) for c in plan.conflicts] == [
            ("translation", "ชาแฮอิน", "ชาเฮอิน")
        ]
        assert plan.order == ["차해인"] and "차해인" not in plan.merged

    def test_two_genders_are_a_gender_conflict_even_with_one_translation(self):
        plan = plan_merge(
            [E("유진", "ยูจิน", type="character", gender="male")], None,
            [E("유진", "ยูจิน", type="character", gender="female")],
        )
        assert [c.kind for c in plan.conflicts] == ["gender"]

    def test_an_empty_gender_is_filled_not_contested(self):
        conflict = Conflict("유진", E("유진", "A", gender=""), E("유진", "B", gender="female"))
        assert conflict.kind == "translation"


def test_combine_keeps_this_side_and_fills_from_the_other():
    entry = combine(E("마나석", "หินมานา", note="x"), E("마나석", "มานาสโตน", type="item", note="y"))
    assert (entry.target, entry.type, entry.note) == ("หินมานา", "item", "x / y")


class TestReconcile:
    def test_an_edit_made_during_the_sync_survives_it(self):
        snapshot = [E("마나", "มานา"), E("길드", "กิลด์")]
        current = [E("마나", "พลังเวท"), E("길드", "กิลด์"), E("포션", "โพชั่น")]  # edited + added
        synced = [E("마나", "มานา"), E("길드", "สมาคม"), E("던전", "ดันเจี้ยน")]
        result = {e.source: e.target for e in reconcile_after_sync(snapshot, current, synced)}
        assert result == {"마나": "พลังเวท", "길드": "สมาคม", "던전": "ดันเจี้ยน", "포션": "โพชั่น"}

    def test_a_term_deleted_during_the_sync_stays_deleted(self):
        snapshot = [E("마나", "มานา")]
        result = reconcile_after_sync(snapshot, [], [E("마나", "มานา")])
        assert result == []


class TestBase:
    def test_a_base_from_another_sheet_is_no_base(self, tmp_path):
        path = str(tmp_path / "s.syncbase")
        save_base(path, "https://a/exec", "rev1", by_key([E("마나", "มานา")]))
        assert set(load_base(path, "https://a/exec")) == {"마나"}
        assert load_base(path, "https://b/exec") is None

    def test_the_base_file_is_never_listed_as_a_glossary(self, tmp_path):
        manager = GlossaryManager(base_dir=str(tmp_path))
        manager.create_profile("Solo")
        save_base(manager.sync_base_path(), "https://a/exec", "r", {})
        assert manager.list_profiles() == ["Solo"]

    def test_renaming_or_deleting_a_series_forgets_what_was_agreed(self, tmp_path):
        manager = GlossaryManager(base_dir=str(tmp_path))
        manager.create_profile("Solo")
        save_base(manager.sync_base_path(), "https://a/exec", "r", {})
        manager.rename_profile("Solo Leveling")
        assert not os.path.exists(manager.sync_base_path("Solo"))
        save_base(manager.sync_base_path(), "https://a/exec", "r", {})
        manager.delete_profile()
        assert not os.path.exists(manager.sync_base_path("Solo Leveling"))

    def test_sync_settings_survive_a_restart(self, tmp_path):
        manager = GlossaryManager(base_dir=str(tmp_path))
        manager.sync_url, manager.sync_token, manager.sync_name = "https://a/exec", "t", "Mint"
        manager.save()
        again = GlossaryManager(base_dir=str(tmp_path))
        assert (again.sync_url, again.sync_token, again.sync_name) == ("https://a/exec", "t", "Mint")


class TestAiReferee:
    CONFLICTS = [
        Conflict("차해인", E("차해인", "ชาแฮอิน", type="character", gender="female", note="S rank"),
                 E("차해인", "ชาเฮอิน", type="character", gender="female")),
        Conflict("게이트", E("게이트", "เกต"), E("게이트", "ประตูมิติ")),
    ]

    def test_the_prompt_shows_a_and_b_and_never_whose_they_are(self):
        prompt = build_conflict_prompt(self.CONFLICTS, [E("성진우", "ซองจินอู")])
        assert "성진우 = ซองจินอู" in prompt
        items = json.loads(prompt.split("Terms to decide:\n", 1)[1])
        assert items[0] == {"source": "차해인", "type": "character", "A": "ชาแฮอิน",
                            "B": "ชาเฮอิน", "gender": "female", "note": "S rank"}
        assert "mine" not in prompt.lower() and "team" not in prompt.lower()

    def test_the_reply_is_matched_by_term_and_garbage_is_left_undecided(self):
        reply = "```json\n" + json.dumps([
            {"source": "차해인", "target": "ชาแฮอิน", "reason": "แฮ = 해"},
            {"source": "게이트", "target": ""},           # empty: undecided
            {"source": "모르는말", "target": "x"},         # not asked
        ], ensure_ascii=False) + "\n```"
        assert parse_conflict_reply(reply, self.CONFLICTS) == {"차해인": ("ชาแฮอิน", "แฮ = 해")}

    def test_a_form_of_address_is_given_its_gender(self):
        conflicts = [Conflict("아가씨", E("아가씨", "คุณหนู"), E("아가씨", "คุณชาย"))]
        reply = json.dumps([{"source": "아가씨", "target": "คุณชาย"}], ensure_ascii=False)
        assert parse_conflict_reply(reply, conflicts)["아가씨"][0] == "คุณหนู"

    def test_the_configured_llm_is_asked_in_batches(self, monkeypatch):
        import types

        from modules.translation.base import LLMTranslation
        import modules.translation.processor as processor
        from modules.utils import glossary_sync

        calls = []

        class Engine(LLMTranslation):
            img_as_llm_input = True

            def initialize(self, *a, **k):
                pass

            def translate(self, *a, **k):
                return {}

            def _perform_translation(self, user_prompt, system_prompt, image):
                items = json.loads(user_prompt.split("Terms to decide:\n", 1)[1])
                calls.append((len(items), system_prompt, image))
                return json.dumps([{"source": i["source"], "target": i["B"]} for i in items])

        class FakeTranslator:
            def __init__(self, *a, **k):
                self.engine = Engine()
                self.source_lang_en, self.target_lang_en = "Korean", "Thai"

        monkeypatch.setattr(processor, "Translator", FakeTranslator)
        monkeypatch.setattr(glossary_sync, "AI_BATCH", 2)
        combo = types.SimpleNamespace(currentText=lambda: "x")
        main = types.SimpleNamespace(s_combo=combo, t_combo=combo)
        conflicts = [Conflict(f"t{i}", E(f"t{i}", "a"), E(f"t{i}", f"b{i}")) for i in range(5)]
        answers = glossary_sync.resolve_conflicts_with_ai(main, conflicts, [])
        assert [n for n, _, _ in calls] == [2, 2, 1]
        assert "from Korean into Thai" in calls[0][1] and calls[0][2] is None
        assert answers["t4"] == ("b4", "")

    def test_a_traditional_translator_cannot_referee(self, monkeypatch):
        import types

        import modules.translation.processor as processor
        from modules.utils import glossary_sync

        class FakeTranslator:
            def __init__(self, *a, **k):
                self.engine = object()
                self.source_lang_en = self.target_lang_en = ""

        monkeypatch.setattr(processor, "Translator", FakeTranslator)
        combo = types.SimpleNamespace(currentText=lambda: "x")
        with pytest.raises(RuntimeError, match="AI translator"):
            glossary_sync.resolve_conflicts_with_ai(
                types.SimpleNamespace(s_combo=combo, t_combo=combo), self.CONFLICTS, []
            )


class TestGlossaryPageSync:
    @pytest.fixture
    def page(self, qapp, tmp_path, monkeypatch):
        from app.ui.settings import glossary_page

        monkeypatch.setattr(glossary_page, "GlossaryManager",
                            lambda: GlossaryManager(base_dir=str(tmp_path)))
        page = glossary_page.GlossaryPage()
        page.manager.create_profile("Solo")
        page.manager.sync_url, page.manager.sync_token = "https://a/exec", "t"
        shown = []
        monkeypatch.setattr(glossary_page.QtWidgets.QMessageBox, "information",
                            lambda *a: shown.append(a[2]))
        monkeypatch.setattr(glossary_page.QtWidgets.QMessageBox, "warning",
                            lambda *a: shown.append(a[2]))
        page.shown = shown
        yield page
        page.deleteLater()

    @staticmethod
    def run_sync(page, qapp, **kw):
        from PySide6.QtCore import QThreadPool

        page.sync_with_team(**kw)
        assert not page.sync_button.isEnabled() and not page.profile_combo.isEnabled()
        QThreadPool.globalInstance().waitForDone(10000)
        for _ in range(20):
            qapp.processEvents()

    def test_a_sync_lands_in_the_glossary_and_is_remembered(self, page, qapp, monkeypatch):
        from modules.utils import glossary_sync as gs

        page.manager.upsert(E("마나", "มานา"))
        seen = {}

        def fake_sync(client, sheet, local, base, user, resolver=None, manual=None):
            seen.update(sheet=sheet, local=[e.source for e in local], base=base, url=client.url)
            merged = local + [E("길드", "กิลด์")]
            plan = gs.plan_merge(local, base, merged)
            return gs.SyncOutcome(entries=merged, base=by_key(merged), rev="r1", plan=plan,
                                  resolved=[gs.Resolved("게이트", "เกต", "ประตู", "ประตูมิติ", "")])

        monkeypatch.setattr(gs, "sync_profile", fake_sync)
        self.run_sync(page, qapp)

        assert seen == {"sheet": "Solo", "local": ["마나"], "base": None, "url": "https://a/exec"}
        assert {e.source for e in page.manager.entries} == {"마나", "길드"}
        assert set(load_base(page.manager.sync_base_path(), "https://a/exec")) == {"마나", "길드"}
        assert page.sync_button.isEnabled() and page.profile_combo.isEnabled()
        assert page.table.rowCount() == 2
        assert "เกต / ประตู → ประตูมิติ" in page.shown[0]

    def test_held_terms_are_put_to_the_user_and_synced_with_their_choice(self, page, qapp, monkeypatch):
        from app.ui.settings import glossary_page
        from modules.utils import glossary_sync as gs

        mine = E("유진", "ยูจิน", type="character", gender="male")
        theirs = E("유진", "ยูจิน", type="character", gender="female")
        page.manager.upsert(mine)
        manuals = []

        def fake_sync(client, sheet, local, base, user, resolver=None, manual=None):
            manuals.append(manual)
            plan = gs.plan_merge(local, base, [theirs])
            held = [] if manual else plan.conflicts
            entries = [manual["유진"]] if manual else local
            return gs.SyncOutcome(entries=entries, base={}, rev="r", plan=plan, held=held)

        def choose_team(dialog):
            dialog.choices[0].setCurrentIndex(1)
            return glossary_page.QtWidgets.QDialog.DialogCode.Accepted

        monkeypatch.setattr(gs, "sync_profile", fake_sync)
        monkeypatch.setattr(glossary_page.GlossaryConflictDialog, "exec", choose_team)
        self.run_sync(page, qapp)
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(10000)
        for _ in range(20):
            qapp.processEvents()

        assert manuals[0] is None and manuals[1]["유진"].gender == "female"
        assert page.manager.find("유진").gender == "female"

    def test_a_failure_is_reported_and_unlocks_the_page(self, page, qapp, monkeypatch):
        from modules.utils import glossary_sync as gs

        def fail(*a, **k):
            raise gs.SyncAuthError("The team glossary refused the token.")

        monkeypatch.setattr(gs, "sync_profile", fail)
        self.run_sync(page, qapp)
        assert "refused the token" in page.shown[0]
        assert page.sync_button.isEnabled() and page.profile_combo.isEnabled()

    def test_without_a_url_the_setup_opens_first(self, page, monkeypatch):
        from app.ui.settings import glossary_page

        page.manager.sync_url = ""
        opened = []
        monkeypatch.setattr(glossary_page.GlossarySyncSetupDialog, "exec",
                            lambda d: opened.append(d) or glossary_page.QtWidgets.QDialog.DialogCode.Rejected)
        page.sync_with_team()
        assert opened and page.sync_button.isEnabled()

    def test_copy_script_puts_the_apps_script_on_the_clipboard(self, page, qapp):
        from app.ui.settings.glossary_page import GlossarySyncSetupDialog

        dialog = GlossarySyncSetupDialog(page.manager, page)
        dialog.copy_script()
        assert "function doPost(e)" in qapp.clipboard().text()
        dialog.deleteLater()
