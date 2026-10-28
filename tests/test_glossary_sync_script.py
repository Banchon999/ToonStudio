"""Two team members syncing a glossary through the real Apps Script.

resources/glossary_sync/Code.gs runs under Node (tests/js/apps_script_server.js)
behind a server that answers like an Apps Script web app: doPost runs on the
POST and the result is served to a GET at the 302's Location. So these tests
cover the client, the script and the merge together; what they cannot cover
is Google itself (deployment access, quotas), which needs a real sheet.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import requests

from modules.utils.glossary import GlossaryEntry, GlossaryManager
from modules.utils.glossary_sync import (
    APPS_SCRIPT_PATH, GlossarySyncClient, SyncAuthError, SyncError,
    load_base, reconcile_after_sync, save_base, sync_profile,
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")

TOKEN = "team-secret"
SHEET = "Solo Leveling"
URL = "https://script.test/macros/s/abc/exec"
HARNESS = Path(__file__).parent / "js" / "apps_script_server.js"


@pytest.fixture
def server():
    proc = subprocess.Popen(
        ["node", str(HARNESS), APPS_SCRIPT_PATH, TOKEN],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        port = int(proc.stdout.readline().strip())
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.kill()
        proc.wait()


class LocalSession(requests.Session):
    """Sends the web app's https:// address to the local harness instead."""

    def __init__(self, base):
        super().__init__()
        self.trust_env = False  # never through the environment's proxy
        self.base = base
        self.calls = []

    def request(self, method, url, *args, **kwargs):
        url = url.replace("https://script.test/macros/s/abc", self.base)
        self.calls.append((method, url))
        return super().request(method, url, *args, **kwargs)


class Member:
    """One translator's machine: their own glossary, base and client."""

    def __init__(self, tmp_path, server, name, token=TOKEN):
        self.name = name
        self.manager = GlossaryManager(base_dir=str(tmp_path / name))
        self.manager.create_profile(SHEET)
        self.session = LocalSession(server)
        self.client = GlossarySyncClient(URL, token, session=self.session)

    def add(self, source, target, **kw):
        self.manager.upsert(GlossaryEntry(source=source, target=target, **kw))

    def sync(self, resolver=None, manual=None):
        path = self.manager.sync_base_path()
        snapshot = list(self.manager.entries)
        outcome = sync_profile(
            self.client, SHEET, snapshot, load_base(path, URL), self.name,
            resolver=resolver, manual=manual, now=lambda: "2026-10-28 12:00:00",
        )
        self.manager.entries = reconcile_after_sync(snapshot, self.manager.entries, outcome.entries)
        self.manager.save()
        save_base(path, URL, outcome.rev, outcome.base)
        return outcome

    def targets(self):
        return {e.source: e.target for e in self.manager.entries}


def dump(server):
    return requests.get(f"{server}/__dump", params={"sheet": SHEET}, proxies={"http": None}).json()


def edit_cell(server, row, column, value):
    requests.post(
        f"{server}/__edit", json={"sheet": SHEET, "row": row, "column": column, "value": value},
        proxies={"http": None},
    )


def test_terms_travel_both_ways_and_the_redirect_is_followed_as_a_get(tmp_path, server):
    a, b = Member(tmp_path, server, "Mint"), Member(tmp_path, server, "Ploy")
    a.add("성진우", "ซองจินอู", type="character", gender="male")
    a.sync()

    grid = dump(server)
    assert grid[0][:6] == ["source", "target", "type", "gender", "note", "aliases"]
    assert grid[1][:4] == ["성진우", "ซองจินอู", "character", "male"]
    assert grid[1][6] == "Mint"  # who changed it

    # The POST is answered with a redirect that must be fetched, not re-posted.
    methods = [m for m, _ in a.session.calls]
    assert methods[:2] == ["POST", "GET"]

    b.add("헌터 협회", "สมาคมฮันเตอร์", type="organization")
    b.sync()
    assert b.targets() == {"성진우": "ซองจินอู", "헌터 협회": "สมาคมฮันเตอร์"}
    a.sync()
    assert a.targets() == b.targets()


def test_an_edit_on_one_side_wins_over_the_unchanged_other(tmp_path, server):
    a, b = Member(tmp_path, server, "Mint"), Member(tmp_path, server, "Ploy")
    a.add("게이트", "เกต")
    a.sync()
    b.sync()

    b.add("게이트", "ประตูมิติ")  # Ploy retranslates; Mint touches nothing
    b.sync()
    outcome = a.sync()
    assert a.targets()["게이트"] == "ประตูมิติ"
    assert outcome.plan.pulled == 1 and not outcome.plan.conflicts


def test_a_deletion_travels_but_never_beats_an_edit(tmp_path, server):
    a, b = Member(tmp_path, server, "Mint"), Member(tmp_path, server, "Ploy")
    a.add("마나", "มานา")
    a.add("던전", "ดันเจี้ยน")
    a.sync()
    b.sync()

    a.manager.remove(["마나", "던전"])
    b.add("던전", "ดันเจียน")  # edited on the other side meanwhile
    a.sync()
    b.sync()
    assert "마나" not in b.targets()            # deleted, untouched elsewhere: gone
    assert b.targets()["던전"] == "ดันเจียน"     # deleted vs edited: the edit stays
    a.sync()
    assert a.targets() == {"던전": "ดันเจียน"}


def test_same_translation_on_both_sides_is_combined_without_the_ai(tmp_path, server):
    a, b = Member(tmp_path, server, "Mint"), Member(tmp_path, server, "Ploy")
    a.add("한도윤", "ฮันโดยุน", type="character", note="main lead", aliases=["도윤"])
    b.add("한도윤", "ฮันโดยุน", type="character", gender="male", aliases=["윤이"])
    a.sync()

    def resolver(conflicts, reference):
        raise AssertionError("nothing to ask")

    outcome = b.sync(resolver=resolver)
    entry = b.manager.find("한도윤")
    assert (entry.gender, entry.note, entry.aliases) == ("male", "main lead", ["윤이", "도윤"])
    assert outcome.plan.combined == 1


def test_different_translations_go_to_the_ai_and_its_choice_reaches_everyone(tmp_path, server):
    a, b = Member(tmp_path, server, "Mint"), Member(tmp_path, server, "Ploy")
    a.add("차해인", "ชาแฮอิน", type="character", gender="female")
    a.sync()
    b.add("차해인", "ชาเฮอิน", type="character", gender="female")

    asked = []

    def resolver(conflicts, reference):
        asked.extend((c.local.target, c.remote.target) for c in conflicts)
        return {conflicts[0].key: ("ชาแฮอิน", "แฮ is the usual spelling of 해")}

    outcome = b.sync(resolver=resolver)
    assert asked == [("ชาเฮอิน", "ชาแฮอิน")]
    assert [r.chosen for r in outcome.resolved] == ["ชาแฮอิน"]
    assert b.targets()["차해인"] == "ชาแฮอิน"
    a.sync()
    assert a.targets()["차해인"] == "ชาแฮอิน"
    assert dump(server)[1][1] == "ชาแฮอิน"


def test_a_gender_disagreement_waits_for_a_person(tmp_path, server):
    a, b = Member(tmp_path, server, "Mint"), Member(tmp_path, server, "Ploy")
    a.add("유진", "ยูจิน", type="character", gender="male")
    a.sync()
    b.add("유진", "ยูจิน", type="character", gender="female")

    outcome = b.sync(resolver=lambda c, r: pytest.fail("a model cannot know who someone is"))
    assert [c.key for c in outcome.held] == ["유진"]
    assert b.manager.find("유진").gender == "female"    # each side keeps its own…
    assert dump(server)[1][3] == "male"
    assert b.sync().held                                 # …and it stays a conflict

    choice = b.manager.find("유진")
    b.sync(manual={"유진": GlossaryEntry("유진", "ยูจิน", type="character", gender=choice.gender)})
    a.sync()
    assert a.manager.find("유진").gender == "female"


def test_an_ai_failure_holds_the_conflicts_and_syncs_the_rest(tmp_path, server):
    a, b = Member(tmp_path, server, "Mint"), Member(tmp_path, server, "Ploy")
    a.add("길드", "กิลด์")
    a.sync()
    b.add("길드", "สมาคม")
    b.add("포션", "โพชั่น")

    def broken(conflicts, reference):
        raise RuntimeError("401 Missing Authentication header")

    outcome = b.sync(resolver=broken)
    assert "401" in outcome.ai_error
    assert [c.key for c in outcome.held] == ["길드"]
    a.sync()
    assert a.targets() == {"길드": "กิลด์", "포션": "โพชั่น"}


def test_a_hand_edit_in_the_sheet_is_picked_up(tmp_path, server):
    a = Member(tmp_path, server, "Mint")
    a.add("S급", "ระดับ S")
    a.sync()
    edit_cell(server, 2, 2, "แรงก์ S")
    a.sync()
    assert a.targets()["S급"] == "แรงก์ S"


def test_a_tab_changed_between_pull_and_push_is_merged_again(tmp_path, server):
    a, b = Member(tmp_path, server, "Mint"), Member(tmp_path, server, "Ploy")
    a.add("레벨업", "เลเวลอัป")
    a.sync()
    b.sync()
    b.add("스킬", "สกิล")

    pull = b.client.pull
    raced = []

    def pull_then_someone_else_writes(sheet):
        rows, rev = pull(sheet)
        if not raced:
            raced.append(True)
            a.add("퀘스트", "เควสต์")
            a.sync()
        return rows, rev

    b.client.pull = pull_then_someone_else_writes
    b.sync()
    a.sync()
    expected = {"레벨업": "เลเวลอัป", "스킬": "สกิล", "퀘스트": "เควสต์"}
    assert a.targets() == expected and b.targets() == expected


def test_text_that_sheets_would_reinterpret_round_trips(tmp_path, server):
    a, b = Member(tmp_path, server, "Mint"), Member(tmp_path, server, "Ploy")
    a.add("1990", "ปี 1990")
    a.add("=마왕=", "=จอมมาร=")
    a.sync()
    b.sync()
    assert b.targets() == {"1990": "ปี 1990", "=마왕=": "=จอมมาร="}
    assert not a.sync().pushed_rows  # nothing came back changed


def test_a_wrong_token_is_refused(tmp_path, server):
    stranger = Member(tmp_path, server, "Stranger", token="guess")
    with pytest.raises(SyncAuthError):
        stranger.sync()


def test_a_script_left_without_a_token_says_so(tmp_path):
    proc = subprocess.Popen(
        ["node", str(HARNESS), APPS_SCRIPT_PATH, "CHANGE-ME"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        base = f"http://127.0.0.1:{int(proc.stdout.readline())}"
        client = GlossarySyncClient(URL, "CHANGE-ME", session=LocalSession(base))
        with pytest.raises(SyncError, match="TOKEN"):
            client.pull(SHEET)
    finally:
        proc.kill()
        proc.wait()


def test_doget_identifies_the_service(server):
    data = requests.get(f"{server}/exec", proxies={"http": None}).json()
    assert data == {"ok": True, "service": "toon-studio-glossary", "api": 1}
    # The harness swaps the token in by this exact line; the shipped script keeps it.
    assert "const TOKEN = 'CHANGE-ME';" in Path(APPS_SCRIPT_PATH).read_text(encoding="utf-8")
