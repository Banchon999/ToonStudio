"""Sharing a series glossary with a team through a Google Sheet.

The sheet is reached through a small Apps Script web app the team deploys on
it (``resources/glossary_sync/Code.gs``), one tab per glossary profile. That
was chosen over the Sheets API on purpose: the API needs every translator to
sign in with OAuth, and a consent screen left in "Testing" — which is where an
unverified app with a spreadsheet scope stays — issues refresh tokens that
expire after seven days. The web app runs as the sheet's owner; the app only
needs its URL and a shared token.

Syncing is a three-way merge per term, keyed by ``term_key``: this machine's
glossary, the team's, and the state both had after the last sync (the *base*,
stored beside the profile). A side that still matches the base did not change,
so the other side wins; that is how edits and deletions travel without
anyone's work being overwritten. Where both sides changed the same term:

- same translation → the entries are combined (aliases joined, an empty gender
  or note filled from the other side);
- different translation → the AI translator picks one or writes a better one
  (``resolve_conflicts_with_ai``), seeing the two only as A and B;
- different gender → held for a person: a model has no evidence about who a
  character is from two glossary rows, and gender decides ครับ/ค่ะ.

A held term keeps this machine's value here and the team's value in the sheet,
and keeps its old base, so it comes back as a conflict until someone decides.

Pushing is optimistic: the push names the revision (a hash of the tab's rows)
the merge was based on, and the script refuses it under its lock if the tab
changed meanwhile — another member's sync, or a hand edit in the sheet — and
the merge is redone against the new rows.

Everything here except ``resolve_conflicts_with_ai`` is Qt-free.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Callable

from .glossary import GlossaryEntry, normalize_term, term_key
from .thai_speech import fix_address_gender

logger = logging.getLogger(__name__)

#: Columns of a profile's tab, in order. The script reads them by header name,
#: so a team member reordering columns by hand does not scramble the glossary.
SHEET_COLUMNS = ["source", "target", "type", "gender", "note", "aliases", "updated_by", "updated_at"]

#: Version of the request/response shape shared with Code.gs.
API_VERSION = 1

#: The script the team pastes into its sheet. resources/ sits next to modules/
#: in a checkout and in a frozen build alike (--add-data resources).
APPS_SCRIPT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "resources", "glossary_sync", "Code.gs")
)

#: Conflicts sent to the model per request; the reply has to fit the output budget.
AI_BATCH = 40

#: Agreed entries listed in the AI request so its choice follows the series'
#: naming conventions. More costs tokens without changing the answer.
AI_REFERENCE_LIMIT = 300

#: How many times a push refused because the tab changed meanwhile is redone.
MAX_ATTEMPTS = 3


class SyncError(RuntimeError):
    """A sync that could not finish. The message is meant for the user."""


class SyncAuthError(SyncError):
    """The script refused the token."""


class SyncConflict(SyncError):
    """The tab changed between pull and push; pull and merge again."""


# Entries ↔ sheet rows


def signature(entry: GlossaryEntry) -> tuple:
    """Everything that makes two entries say the same thing."""
    return (
        normalize_term(entry.source),
        normalize_term(entry.target),
        entry.type or "term",
        entry.gender or "",
        (entry.note or "").strip(),
        tuple(entry.aliases or ()),
    )


def same(a: GlossaryEntry | None, b: GlossaryEntry | None) -> bool:
    if a is None or b is None:
        return a is b
    return signature(a) == signature(b)


def entry_to_row(entry: GlossaryEntry) -> dict[str, str]:
    return {
        "source": entry.source,
        "target": entry.target,
        "type": entry.type or "term",
        "gender": entry.gender or "",
        "note": entry.note or "",
        "aliases": ", ".join(entry.aliases or []),
    }


def rows_to_entries(rows) -> tuple[list[GlossaryEntry], dict[str, dict[str, str]]]:
    """Entries from the tab's rows, plus who last changed each one and when.

    A row without a source or target is skipped, as on import; a term listed
    twice keeps its first row — people do paste rows into a shared sheet.
    """
    entries: list[GlossaryEntry] = []
    stamps: dict[str, dict[str, str]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        entry = GlossaryEntry.from_dict(row)
        if entry is None or entry.key in stamps:
            continue
        entries.append(entry)
        stamps[entry.key] = {
            "updated_by": str(row.get("updated_by", "") or ""),
            "updated_at": str(row.get("updated_at", "") or ""),
        }
    return entries, stamps


def stamped_rows(
    entries: list[GlossaryEntry],
    remote: dict[str, GlossaryEntry],
    stamps: dict[str, dict[str, str]],
    user: str,
    now: str,
) -> list[dict[str, str]]:
    """Rows to write: an unchanged term keeps its stamp, a changed one gets ours."""
    rows = []
    for entry in entries:
        row = entry_to_row(entry)
        if same(entry, remote.get(entry.key)):
            row.update(stamps.get(entry.key, {"updated_by": "", "updated_at": ""}))
        else:
            row.update({"updated_by": user, "updated_at": now})
        rows.append(row)
    return rows


# The merge


@dataclass
class Conflict:
    """A term both sides changed into something different."""

    key: str
    local: GlossaryEntry
    remote: GlossaryEntry

    @property
    def kind(self) -> str:
        """"gender" when the two disagree about who a character is, else "translation"."""
        genders = {self.local.gender, self.remote.gender} - {""}
        return "gender" if len(genders) > 1 else "translation"


@dataclass
class MergePlan:
    """What the three-way merge decided before any conflict is resolved."""

    merged: dict[str, GlossaryEntry]  # every decided term; conflicts are not in it
    order: list[str]  # keys of merged + conflicts, in display order
    conflicts: list[Conflict]
    pulled: int = 0     # terms this machine takes from the team (new or changed)
    pushed: int = 0     # terms the team takes from this machine
    deleted_here: int = 0   # deleted by the team, so deleted here
    deleted_there: int = 0  # deleted here, so deleted in the sheet
    combined: int = 0   # same translation on both sides, fields joined


def combine(local: GlossaryEntry, remote: GlossaryEntry, target: str | None = None) -> GlossaryEntry:
    """One entry from two descriptions of the same term.

    This machine's wording wins wherever both have one; the other side fills
    what this side left empty. Aliases are the union, notes are both.
    """
    entry_type = local.type
    if (local.type or "term") == "term" and remote.type and remote.type != "term":
        entry_type = remote.type
    note_l, note_r = (local.note or "").strip(), (remote.note or "").strip()
    if note_l and note_r and note_l != note_r:
        note = f"{note_l} / {note_r}"
    else:
        note = note_l or note_r
    aliases = list(local.aliases or [])
    seen = {term_key(a.partition("=")[0]) for a in aliases}
    for alias in remote.aliases or []:
        key = term_key(alias.partition("=")[0])
        if key not in seen:
            seen.add(key)
            aliases.append(alias)
    return replace(
        local,
        target=target if target is not None else local.target,
        type=entry_type or "term",
        gender=local.gender or remote.gender,
        note=note,
        aliases=aliases,
    )


def plan_merge(
    local: list[GlossaryEntry],
    base: dict[str, GlossaryEntry] | None,
    remote: list[GlossaryEntry],
) -> MergePlan:
    """Three-way merge of this machine's glossary with the team's.

    ``base`` is what both held after the last sync, or None before the first
    one — then nothing counts as deleted and every disagreement is a conflict.
    A change beats a deletion on either side: work is never lost to a sync.
    """
    base = base or {}
    local_by = {e.key: e for e in local if e.key}
    remote_by = {e.key: e for e in remote if e.key}
    order = list(dict.fromkeys([e.key for e in local if e.key] + [e.key for e in remote if e.key]))
    plan = MergePlan(merged={}, order=[], conflicts=[])

    for key in order:
        mine, theirs, was = local_by.get(key), remote_by.get(key), base.get(key)
        if mine is not None and theirs is not None:
            if same(mine, theirs):
                plan.merged[key] = mine
            elif was is not None and same(mine, was):
                plan.merged[key] = theirs
                plan.pulled += 1
            elif was is not None and same(theirs, was):
                plan.merged[key] = mine
                plan.pushed += 1
            elif normalize_term(mine.target) == normalize_term(theirs.target):
                conflict = Conflict(key, mine, theirs)
                if conflict.kind == "gender":
                    plan.conflicts.append(conflict)
                else:
                    plan.merged[key] = combine(mine, theirs)
                    plan.combined += 1
            else:
                plan.conflicts.append(Conflict(key, mine, theirs))
        elif mine is not None:
            if was is not None and same(mine, was):
                plan.deleted_here += 1
                continue
            plan.merged[key] = mine
            plan.pushed += 1
        else:
            if was is not None and same(theirs, was):
                plan.deleted_there += 1
                continue
            plan.merged[key] = theirs
            plan.pulled += 1
    conflicted = {c.key for c in plan.conflicts}
    plan.order = [k for k in order if k in plan.merged or k in conflicted]
    return plan


# Resolving conflicts


#: (conflicts, agreed entries for reference) → {key: (target, reason)}
Resolver = Callable[[list[Conflict], list[GlossaryEntry]], dict[str, tuple[str, str]]]


@dataclass
class Resolved:
    """A translation conflict the AI settled, for the report."""

    source: str
    mine: str
    team: str
    chosen: str
    reason: str


@dataclass
class SyncOutcome:
    """What a finished sync leaves on this machine."""

    entries: list[GlossaryEntry]        # the local glossary after the sync
    base: dict[str, GlossaryEntry]      # what to remember as the common state
    rev: str
    plan: MergePlan
    resolved: list[Resolved] = field(default_factory=list)
    held: list[Conflict] = field(default_factory=list)
    ai_error: str = ""
    pushed_rows: int = 0  # 0 when nothing had to be written to the sheet


def _resolution_cache_key(conflict: Conflict) -> tuple:
    return conflict.key, signature(conflict.local), signature(conflict.remote)


def sync_profile(
    client,
    sheet: str,
    local: list[GlossaryEntry],
    base: dict[str, GlossaryEntry] | None,
    user: str,
    resolver: Resolver | None = None,
    manual: dict[str, GlossaryEntry] | None = None,
    now: Callable[[], str] | None = None,
) -> SyncOutcome:
    """Pull the team's tab, merge, settle what can be settled, and push.

    ``manual`` holds the entries a person chose for held conflicts (by key);
    they are used before the resolver is asked anything. The resolver is only
    asked about translation conflicts, once per conflict across retries.
    """
    now = now or (lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    manual = manual or {}
    cache: dict[tuple, tuple[str, str]] = {}
    ai_error = ""

    for _attempt in range(MAX_ATTEMPTS):
        rows, rev = client.pull(sheet)
        remote, stamps = rows_to_entries(rows)
        remote_by = {e.key: e for e in remote}
        plan = plan_merge(local, base, remote)

        decided: dict[str, GlossaryEntry] = {}
        resolved: list[Resolved] = []
        ask: list[Conflict] = []
        for conflict in plan.conflicts:
            if conflict.key in manual:
                decided[conflict.key] = manual[conflict.key]
            elif conflict.kind == "translation":
                if _resolution_cache_key(conflict) not in cache:
                    ask.append(conflict)

        if ask and resolver is not None and not ai_error:
            reference = [plan.merged[k] for k in plan.order if k in plan.merged][:AI_REFERENCE_LIMIT]
            try:
                answers = resolver(ask, reference)
            except Exception as e:  # the merge still goes ahead without them
                logger.exception("AI glossary conflict resolution failed")
                ai_error = str(e) or e.__class__.__name__
                answers = {}
            for conflict in ask:
                if conflict.key in answers:
                    cache[_resolution_cache_key(conflict)] = answers[conflict.key]

        held: list[Conflict] = []
        for conflict in plan.conflicts:
            if conflict.key in decided:
                continue
            answer = cache.get(_resolution_cache_key(conflict)) if conflict.kind == "translation" else None
            if answer is None:
                held.append(conflict)
                continue
            target, reason = answer
            decided[conflict.key] = combine(conflict.local, conflict.remote, target=target)
            resolved.append(Resolved(
                conflict.local.source, conflict.local.target, conflict.remote.target, target, reason,
            ))

        held_keys = {c.key for c in held}
        local_by = {e.key: e for e in local}
        merged = dict(plan.merged)
        merged.update(decided)
        # The sheet keeps the team's value of a held term, this machine keeps its own.
        sheet_entries = [merged[k] if k in merged else remote_by[k] for k in plan.order]
        local_entries = [merged[k] if k in merged else local_by[k] for k in plan.order]

        new_rev, pushed_rows = rev, 0
        if [signature(e) for e in sheet_entries] != [signature(e) for e in remote]:
            out_rows = stamped_rows(sheet_entries, remote_by, stamps, user, now())
            try:
                new_rev = client.push(sheet, out_rows, rev, user)
            except SyncConflict:
                logger.info("Team glossary %r changed during sync; merging again", sheet)
                continue
            pushed_rows = len(out_rows)

        new_base = {k: e for k, e in merged.items()}
        for key in held_keys:
            if base and key in base:
                new_base[key] = base[key]
        return SyncOutcome(
            entries=local_entries, base=new_base, rev=new_rev, plan=plan,
            resolved=resolved, held=held, ai_error=ai_error, pushed_rows=pushed_rows,
        )

    raise SyncError(
        "The team glossary kept changing while syncing. Try again in a moment."
    )


def reconcile_after_sync(
    snapshot: list[GlossaryEntry],
    current: list[GlossaryEntry],
    synced: list[GlossaryEntry],
) -> list[GlossaryEntry]:
    """The sync result, keeping whatever the user changed while it ran.

    The sync worked on ``snapshot``; ``current`` is the glossary now (an edit,
    or terms auto-extraction added meanwhile). A term changed since the
    snapshot keeps its current value and is pushed on the next sync, since it
    now differs from the base.
    """
    before = {e.key: signature(e) for e in snapshot}
    now_by = {e.key: e for e in current}
    touched = {k for k, e in now_by.items() if before.get(k) != signature(e)}
    removed = set(before) - set(now_by)

    result: list[GlossaryEntry] = []
    placed: set[str] = set()
    for entry in synced:
        if entry.key in removed:
            continue
        result.append(now_by[entry.key] if entry.key in touched else entry)
        placed.add(entry.key)
    result.extend(e for e in current if e.key in touched and e.key not in placed)
    return result


# The stored base


def load_base(path: str, url: str) -> dict[str, GlossaryEntry] | None:
    """The common state remembered after the last sync with ``url``, or None.

    A base from a different sheet is no base at all: comparing against it
    would read every term the new sheet lacks as deleted by the team.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("Ignoring unreadable glossary sync base %s: %s", path, e)
        return None
    if not isinstance(data, dict) or data.get("url") != url:
        return None
    entries = [GlossaryEntry.from_dict(raw) for raw in data.get("entries", []) if isinstance(raw, dict)]
    return {e.key: e for e in entries if e is not None}


def save_base(path: str, url: str, rev: str, base: dict[str, GlossaryEntry]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            {"url": url, "rev": rev, "entries": [asdict(e) for e in base.values()]},
            f, ensure_ascii=False, indent=2,
        )
    os.replace(tmp, path)


# The web app


class GlossarySyncClient:
    """Talks to the Apps Script web app (``resources/glossary_sync/Code.gs``).

    Every call is a POST, so the token never lands in a URL or a log. Apps
    Script runs ``doPost`` on the POST and answers 302 to a
    script.googleusercontent.com address that serves the result to a GET.
    The redirect is followed by hand rather than left to ``requests``, whose
    turning POST into GET on a 302 is browser behaviour it could change and
    the script relies on.
    """

    def __init__(self, url: str, token: str, session=None, timeout: float = 60):
        self.url = (url or "").strip()
        self.token = (token or "").strip()
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self.timeout = timeout

    def _call(self, payload: dict) -> dict:
        if not self.url.startswith("https://"):
            raise SyncError("The team glossary address must be the web app URL, starting with https://.")
        body = json.dumps({**payload, "token": self.token, "api": API_VERSION}, ensure_ascii=False)
        try:
            response = self.session.post(
                self.url, data=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=self.timeout, allow_redirects=False,
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location", "")
                if not location:
                    raise SyncError("The team glossary answered with a redirect to nowhere.")
                response = self.session.get(location, timeout=self.timeout)
        except SyncError:
            raise
        except Exception as e:
            raise SyncError(f"Could not reach the team glossary: {e}") from e

        if response.status_code != 200:
            raise SyncError(f"The team glossary answered HTTP {response.status_code}.")
        try:
            data = json.loads(response.text)
        except ValueError:
            # A sign-in page: the web app is not deployed for "Anyone".
            raise SyncError(
                "The team glossary did not answer with data. Deploy the script as a web app "
                "with access for \"Anyone\", and use the URL ending in /exec."
            ) from None
        if not isinstance(data, dict):
            raise SyncError("The team glossary sent an answer this version does not understand.")
        if data.get("ok"):
            return data
        error = data.get("error", "")
        message = data.get("message", "")
        if error == "unauthorized":
            raise SyncAuthError("The team glossary refused the token. Check it matches TOKEN in the script.")
        if error == "conflict":
            raise SyncConflict("The team glossary changed during the sync.")
        if error == "not_configured":
            raise SyncError("The script's TOKEN is not set yet. Set it, then deploy a new version.")
        raise SyncError(f"The team glossary refused the request: {message or error or 'unknown error'}")

    def pull(self, sheet: str) -> tuple[list[dict], str]:
        data = self._call({"action": "pull", "sheet": sheet})
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise SyncError("The team glossary sent no rows.")
        return rows, str(data.get("rev", ""))

    def push(self, sheet: str, rows: list[dict], base_rev: str, user: str = "") -> str:
        data = self._call({
            "action": "push", "sheet": sheet, "rows": rows, "base_rev": base_rev, "user": user,
        })
        return str(data.get("rev", ""))


# The AI referee


CONFLICT_SYSTEM_PROMPT = """You maintain the shared glossary of a team translating a comic series from {source_lang} into {target_lang}.
Two team members gave different {target_lang} translations, A and B, for the same glossary term.
For each term, decide the translation the whole team will use from now on:
- pick A or B, or write a corrected one when both are wrong;
- it must be right for the term's meaning, its type and the character's gender;
- follow the naming and romanisation conventions of the agreed glossary given for reference, and stay consistent with related names in it;
- give the term only, as it would be written in a translated page: no explanation, no brackets, no alternatives.

Respond with ONLY a JSON array, one item per term, in this exact shape:
[{{"source": "<the term exactly as given>", "target": "<the translation to use>", "reason": "<one short sentence>"}}]"""


def build_conflict_prompt(conflicts: list[Conflict], reference: list[GlossaryEntry]) -> str:
    """The user prompt for one batch. A and B are never named as anyone's."""
    parts = []
    if reference:
        lines = "\n".join(f"{e.source} = {e.target}" for e in reference)
        parts.append("Agreed glossary, for reference:\n" + lines)
    items = []
    for c in conflicts:
        item = {
            "source": c.local.source,
            "type": c.local.type if c.local.type != "term" else (c.remote.type or "term"),
            "A": c.local.target,
            "B": c.remote.target,
        }
        gender = c.local.gender or c.remote.gender
        if gender:
            item["gender"] = gender
        notes = [n for n in dict.fromkeys([(c.local.note or "").strip(), (c.remote.note or "").strip()]) if n]
        if notes:
            item["note"] = " / ".join(notes)
        items.append(item)
    parts.append("Terms to decide:\n" + json.dumps(items, ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


def parse_conflict_reply(reply: str, conflicts: list[Conflict]) -> dict[str, tuple[str, str]]:
    """Answers by key; anything the reply leaves out or garbles stays undecided."""
    from .glossary_extractor import _parse_json_array

    wanted = {c.key: c for c in conflicts}
    answers: dict[str, tuple[str, str]] = {}
    for item in _parse_json_array(reply):
        key = term_key(str(item.get("source", "")))
        target = normalize_term(str(item.get("target", "") or ""))
        if key not in wanted or key in answers or not target:
            continue
        source = wanted[key].local.source
        answers[key] = (fix_address_gender(source, target), str(item.get("reason", "") or "").strip())
    return answers


def resolve_conflicts_with_ai(main_page, conflicts: list[Conflict], reference: list[GlossaryEntry]):
    """Ask the configured LLM translator to settle translation conflicts.

    Raises RuntimeError with a user-facing message when no LLM translator is
    selected; the sync then holds the conflicts for a person instead.
    """
    from modules.translation.base import LLMTranslation
    from modules.translation.processor import Translator

    translator = Translator(main_page, main_page.s_combo.currentText(), main_page.t_combo.currentText())
    engine = translator.engine
    if not isinstance(engine, LLMTranslation):
        raise RuntimeError(
            "Settling glossary conflicts needs an AI translator. "
            "Select an LLM translator in Settings > Tools."
        )
    engine.img_as_llm_input = False
    system_prompt = CONFLICT_SYSTEM_PROMPT.format(
        source_lang=translator.source_lang_en or "the source language",
        target_lang=translator.target_lang_en or "the target language",
    )
    answers: dict[str, tuple[str, str]] = {}
    for start in range(0, len(conflicts), AI_BATCH):
        batch = conflicts[start:start + AI_BATCH]
        reply = engine._perform_translation(build_conflict_prompt(batch, reference), system_prompt, None)
        answers.update(parse_conflict_reply(reply, batch))
    return answers
