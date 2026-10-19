"""Who speaks each bubble, decided before translating into Thai.

Thai picks ครับ/ค่ะ and ผม/ดิฉัน by the speaker's gender, which Korean,
Chinese and English do not write into the line. Asked to work out the
speaker while translating, the model credited a bubble to the name inside
it ("죄송해요, 엄마. 준이 시장에 있었어요." said by Mina, given to 준 in 10
runs of 10) and gave an unclear reply to the male lead; measured on a
three-page conversation in all three languages, 9% of Korean bubbles came
out with the wrong particle on pages where the bubble's tail points at a
clearly drawn woman. Asked *only* who speaks, the same model got every one
of those bubbles right (0 wrong in 162). So the speaker is decided first, in
a request of its own, and the translation is handed the answer.

Adapted from NovelTrans's speaker map (the owner's novel translator), where
each quoted line has to be matched back to its translation by order and
position. Here a text block is one bubble, so a block's speaker is simply
its index: no matching, and the fix after translation is per block.

Nothing here talks to a model or imports Qt; `llm/base.py` makes the request.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


MALE, FEMALE, UNKNOWN = "male", "female", "unknown"
SPEECH, THOUGHT = "speech", "thought"


@dataclass
class Speaker:
    name: str = ""
    gender: str = UNKNOWN   # male | female | unknown
    evidence: str = ""
    mode: str = SPEECH      # speech (said to someone) | thought (to no one)

    @property
    def known(self) -> bool:
        return self.gender in (MALE, FEMALE)

    @property
    def thought(self) -> bool:
        return self.mode == THOUGHT


@dataclass
class Character:
    """A glossary character: its gender is authoritative."""
    source: str
    target: str
    gender: str


# Per source language: what shows a speaker's gender in the words. Examples
# from one language are never sent with another's source (NovelTrans measured
# a Chinese passage getting worse with Korean rules).
_GENDER_WORDS = {
    "korean": "오빠/언니 said by a girl or woman, 형/누나 said by a boy or man; 할머니/아주머니/아가씨 "
              "are women, 할아버지/아저씨/총각 men. A name with a particle attached (준이, 준이가, "
              "미나는, 미나한테) is someone talked ABOUT — Korean speakers almost never call "
              "themselves by name.",
    "chinese": "哥哥/姐姐 say nothing about the speaker; 本小姐/人家/奴家 are said by women, "
               "本少爷/老子/在下 mostly by men; 大婶/姑娘/婆婆 are women, 大叔/小伙子/公子 men.",
    "japanese": "俺/僕/ぜ/ぞ are male speech, あたし/わ/のよ female speech; 私 proves nothing.",
    "english": "Titles and kin words name the LISTENER (sir, ma'am, Mom, Sis, bro), not the speaker; "
               "a speaker calls themself someone's sister, mother, wife, son…",
}


def _gender_words(source_lang: str) -> str:
    lang = (source_lang or "").lower()
    for key, words in _GENDER_WORDS.items():
        if key in lang:
            return words
    return ""


def build_speaker_prompt(source_lang: str, texts: list[str], characters: list[Character]) -> str:
    """The request that asks only who speaks each block."""
    chars = "\n".join(
        f"- {c.source} = {c.target}" + (f" ({c.gender})" if c.gender in (MALE, FEMALE) else "")
        for c in characters
    ) or "(none)"
    blocks = "\n".join(f"{i + 1}. {' '.join((t or '').split())}" for i, t in enumerate(texts))
    words = _gender_words(source_lang)
    lang = source_lang or "comic"
    return "\n".join([
        f"You identify who speaks each numbered text block on a {lang} comic page. Do not translate.",
        "",
        "KNOWN CHARACTERS (glossary — their gender is authoritative):",
        chars,
        "",
        "For EACH block decide the speaker:",
        "• Follow the bubble's tail in the image to the figure it points at, and look at that figure.",
        "• Use the conversation: turn-taking, who answers whom, how the speaker addresses the listener.",
        "• A name or form of address inside a block is the person spoken TO. A block that mentions "
        "a character is almost never spoken by that character.",
        *([f"• {words}"] if words else []),
        '• gender: "male" | "female" | "unknown" — "unknown" when nothing on the page shows it.',
        '• mode: "speech" when the block is said aloud TO someone; "thought" when it is addressed to '
        "no one — a thought bubble (cloud outline, a trail of small circles), a character's "
        "first-person inner monologue in a box beside or about them, or talking to oneself. A "
        "normal speech bubble is \"thought\" too when its character is alone in the panel and "
        "the line addresses no one (\"Phew… I have to win.\", \"No, I can't give up!\"): decide "
        "by who it is said to, not by the bubble's shape. Its speaker is still the character.",
        '• Caption boxes that narrate in the third person are "narration", sound effects "sfx" '
        '(both gender "unknown", mode "speech").',
        "",
        f"Return ONLY JSON, exactly {len(texts)} items, in order:",
        '{"blocks":[{"q":1,"evidence":"<what shows who speaks>","speaker":"<name or short description>",'
        '"gender":"male|female|unknown","mode":"speech|thought"}]}',
        "",
        "BLOCKS:",
        blocks,
    ])


def _character_for(name: str, characters: list[Character]) -> Character | None:
    """The glossary character a reported speaker name refers to, if any.

    Matched loosely, as NovelTrans does: a model writes "Mina", "미나 씨" or
    "มินา" for 서미나. The longest matching name wins, so 김철수 is not taken
    for 철수 when both are characters.
    """
    n = " ".join((name or "").split()).casefold()
    if not n:
        return None
    best, best_len = None, 0
    for c in characters:
        for form in (c.source, c.target):
            f = " ".join((form or "").split()).casefold()
            if len(f) < 2:
                continue
            if f in n or n in f:
                if len(f) > best_len:
                    best, best_len = c, len(f)
    return best


def parse_speaker_reply(raw: str, count: int, characters: list[Character]) -> list[Speaker] | None:
    """Read the model's answer: one Speaker per block, or None if unreadable.

    A glossary character's gender wins over the model's, as in NovelTrans:
    the model is the one that guesses.
    """
    text = re.sub(r"```(?:json)?", "", raw or "")
    start, end = text.find("{"), text.rfind("}")
    items = None
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            items = data.get("blocks") if isinstance(data, dict) else None
        except ValueError:
            items = None
    if items is None:
        a, b = text.find("["), text.rfind("]")
        if a >= 0 and b > a:
            try:
                items = json.loads(text[a:b + 1])
            except ValueError:
                return None
    if not isinstance(items, list):
        return None
    by_q = {}
    for pos, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        try:
            q = int(item.get("q", pos + 1))
        except (TypeError, ValueError):
            q = pos + 1
        by_q.setdefault(q, item)
    speakers = []
    for i in range(count):
        item = by_q.get(i + 1, {})
        name = " ".join(str(item.get("speaker") or "").split())
        gender = str(item.get("gender") or "").strip().lower()
        gender = gender if gender in (MALE, FEMALE) else UNKNOWN
        if name.lower() in ("narration", "sfx", "unknown", "-", "?"):
            gender = UNKNOWN
        char = _character_for(name, characters) if gender != UNKNOWN or name else None
        if char is not None and char.gender in (MALE, FEMALE):
            gender = char.gender
        mode = THOUGHT if str(item.get("mode") or "").strip().lower() == THOUGHT else SPEECH
        speakers.append(Speaker(name, gender, " ".join(str(item.get("evidence") or "").split()), mode))
    return speakers


def speaker_map_block(speakers: list[Speaker]) -> str:
    """The speaker map as handed to the translation request.

    The source text is deliberately not repeated: NovelTrans measured a
    model leaving lines untranslated when the map quoted them.
    """
    if not speakers or not any(s.known or s.thought for s in speakers):
        return ""
    lines = []
    for i, s in enumerate(speakers):
        who = s.name or "unknown"
        if s.thought:
            rule = (f"{s.gender + ', ' if s.known else ''}inner thought / talking to oneself → no "
                    "ครับ/ค่ะ at all, self ฉัน or เรา — never ผม/ดิฉัน")
        # The map settles whose gender a particle follows, not whether the
        # line takes one: "male → ครับ, self ผม" for every block put ครับ on
        # casual lines and on a character muttering to himself.
        elif s.gender == MALE:
            rule = ("male → if the line takes a polite particle it is ครับ, never ค่ะ/คะ/ดิฉัน; "
                    "casual speech takes none")
        elif s.gender == FEMALE:
            rule = ("female → if the line takes a polite particle it is ค่ะ/คะ, never ครับ/ผม; "
                    "casual speech takes none")
        else:
            rule = "speaker's gender unknown → no ครับ/ค่ะ"
        lines.append(f"block_{i}: {who} ({rule})")
    return "\n".join([
        "SPEAKER MAP (identified from the page before translating — follow it; it decides each "
        "block's speaker, gender, polite particle and self-pronoun, and the speaker and gender "
        "you return):",
        *lines,
    ])


# After translation: swap a particle or self-pronoun of the wrong gender for
# the right one. Only swaps — whether a line takes a particle at all is the
# translator's call (Korean 반말 takes none).

_P_END = r"(?=$|[\s!?.…,~ๆ\-—)”\"’」』])"
_ROYAL_M = "\u0001"
_HAIR = re.compile(
    "เส้นผม|ทรงผม|สระผม|หวีผม|ผมเผ้า|ผมยาว|ผมสั้น|ผมสี|ปอยผม|มัดผม|ผมหงอก|ผมดำ|"
    "ผมทอง|ผมขาว|ผมแดง|ผมเงิน|ไรผม|โคนผม|ปลายผม|เกล้าผม|ถักผม|ตัดผม|ทำผม"
)


# "ครับ/ค่ะ": a model hedging when it cannot tell who speaks. Never final text.
_HEDGE = re.compile(r"(ครับ|ค่ะ|คะ)\s*/\s*(ครับ|ค่ะ|คะ)")


def _resolve_hedge(text: str, gender: str) -> str:
    def pick(m):
        a, b = m.group(1), m.group(2)
        if gender == MALE:
            return "ครับ"
        if gender == FEMALE:
            return a if a != "ครับ" else b
        return ""
    return _HEDGE.sub(pick, text)


def fix_particles(text: str, gender: str) -> str:
    """text with its ครับ/ค่ะ and ผม/ดิฉัน made to agree with gender.

    Ported from NovelTrans's fixQuoteGender. พ่ะย่ะค่ะ is a man's word and
    ends in ค่ะ; ผม is also hair; คะแนน is not คะ.
    """
    if not text:
        return text
    text = _resolve_hedge(text, gender)
    if gender not in (MALE, FEMALE):
        return text
    t = re.sub("พ่ะย่ะค่ะ|พะยะค่ะ", _ROYAL_M, text)
    if gender == FEMALE:
        t = t.replace("ครับผม", "ค่ะ")
        t = re.sub("ขอรับ" + _P_END, "เจ้าค่ะ", t)
        t = t.replace("นะครับ", "นะคะ")
        t = re.sub(r"ครับ(?=\s*[?？])", "คะ", t)
        t = t.replace("ครับ", "ค่ะ")
        t = t.replace(_ROYAL_M, "เพคะ")
        hair: list[str] = []

        def keep(m):
            hair.append(m.group(0))
            return f"\u0002{len(hair) - 1}\u0002"

        t = _HAIR.sub(keep, t)
        t = t.replace("กระผม", "ดิฉัน")
        t = re.sub(r"(^|[\s“\"「…,])ผม", r"\1ฉัน", t)
        t = re.sub("\u0002(\\d+)\u0002", lambda m: hair[int(m.group(1))], t)
    else:
        t = re.sub("เจ้าค่ะ" + _P_END, "ขอรับ", t)
        t = re.sub("เพคะ" + _P_END, _ROYAL_M, t)
        t = t.replace("นะคะ", "นะครับ")
        t = t.replace("ค่ะ", "ครับ")
        t = re.sub("คะ" + _P_END, "ครับ", t)
        t = t.replace(_ROYAL_M, "พ่ะย่ะค่ะ")
        t = re.sub("ดิฉัน|อิฉัน", "ผม", t)
    return t


def strip_polite(text: str) -> str:
    """A thought as Thai writes one: no polite particle, no polite self-pronoun.

    ครับ/ค่ะ and ผม/ดิฉัน are how a speaker addresses someone; a character
    thinking or talking to themself addresses no one, and Thai comics write
    those lines with ฉัน/เรา and no particle. Since the speaker map (3.1.0)
    told the translation "male → ครับ, self ผม" for every block a character
    was credited with, monologue boxes came back ending in ครับ — 11 of 50 on
    the test pages, against 0 of 50 in 3.0.3. คะแนน is not คะ; hair stays ผม.
    """
    if not text:
        return text
    t = _resolve_hedge(text, UNKNOWN)
    t = t.replace("ครับผม", "")
    t = re.sub("นะ(?:ครับ|คะ|ค่ะ)", "นะ", t)
    t = re.sub("(?:ขอรับ|เจ้าค่ะ|ครับ|ค่ะ)" + _P_END, "", t)
    t = re.sub("คะ" + _P_END, "", t)
    hair: list[str] = []

    def keep(m):
        hair.append(m.group(0))
        return f"\u0002{len(hair) - 1}\u0002"

    t = _HAIR.sub(keep, t)
    t = re.sub("กระผม|ดิฉัน|อิฉัน", "ฉัน", t)
    t = re.sub(r"(^|[\s“\"「…,])ผม", r"\1ฉัน", t)
    t = re.sub("\u0002(\\d+)\u0002", lambda m: hair[int(m.group(1))], t)
    t = re.sub(r"[ \t]+([!?.…,~])", r"\1", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def apply_speaker_map(blk_list, speakers: list[Speaker] | None) -> int:
    """Put the map's speakers on the blocks and fix their particles.

    A block the map knows takes the map's speaker and gender (the request
    that only asked who speaks is the reliable one) and has its wrong-gender
    words swapped. A thought loses its polite particles and pronouns
    whatever the gender. A block the map does not know keeps what the
    translation said, except a hedged "ค่ะ/ครับ", which is dropped. Returns
    how many translations were changed.
    """
    if not speakers:
        return 0
    changed = 0
    for blk, s in zip(blk_list, speakers):
        before = getattr(blk, "translation", "") or ""
        if s.thought:
            if s.known:
                blk.speaker = s.name or getattr(blk, "speaker", "")
                blk.speaker_gender = s.gender
            after = strip_polite(before)
        elif s.known:
            blk.speaker = s.name or getattr(blk, "speaker", "")
            blk.speaker_gender = s.gender
            after = fix_particles(before, s.gender)
        else:
            after = _resolve_hedge(before, UNKNOWN)   # only "ครับ/ค่ะ" is touched
        if after != before:
            blk.translation = after
            changed += 1
    return changed
