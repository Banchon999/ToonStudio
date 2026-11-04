"""How glossary extraction should write names and terms, per source language.

The extraction prompt asked for terms translated "the way a professional
localization would", the same words for every source. NovelTrans measured what
that costs: one prompt bent to fit every language put Chinese names right 2–3
times in 7, and the language's own conventions took it to 6–7 in 7. So each
source gets its own rules, and only its own — Korean examples sent with a
Chinese page are applied to it.

Which language a text is in is read from the text itself (`script_language`)
when the setting says Auto or disagrees with the letters on the page.
Qt-free.
"""

from __future__ import annotations

import re

# Into Thai: the conventions Thai publishers of each kind of comic follow.
_THAI_NAMING = {
    "Korean": "\n".join([
        "NAMES (Korean → Thai): transliterate the way Thai publishers of Korean webtoons and novels do, "
        "syllable by syllable — surnames 김 คิม · 이 อี · 박 พัค · 최 ชเว · 정 จอง · 강 คัง · 조 โจ · 윤 ยุน · "
        "장 จาง · 한 ฮัน · 서 ซอ · 신 ชิน · 송 ซง; given names 민준 มินจุน · 서연 ซอยอน · 지훈 จีฮุน · 하은 ฮาอึน · "
        "진우 จินอู. ㅓ is ออ, ㅡ is อึ, ㅐ/ㅔ are แอ/เอ.",
        "• Sino-Korean names in a Korean story (sects, places, martial arts) are read in KOREAN, never in "
        "Mandarin: 화산 ฮวาซาน (not หัวซาน) · 무당 มูดัง · 소림 โซริม · 천마 ชอนมา.",
        "• A word's meaning follows the story's world: 검 is ดาบ in a modern or hunter story and กระบี่ in "
        "martial arts; 생도 is นักเรียน at a hunter academy and นักเรียนนายร้อย at a military one.",
        "• Skills, ranks, items and organisations with a meaning are translated by meaning; only names "
        "are transliterated.",
    ]),
    "Chinese": "\n".join([
        "NAMES (Chinese → Thai): transliterate from Mandarin the way Thai publishers of Chinese novels and "
        "manhua do — surnames 林 หลิน · 李 หลี่ · 王 หวัง · 张 จาง · 陈 เฉิน · 刘 หลิว · 叶 เย่ · 萧 เซียว.",
        "• Sects, titles and ranks are translated by meaning in the wuxia/xianxia style: XX宗/XX派/XX门 → "
        "สำนักXX (the name part transliterated) · 宗主/掌门 เจ้าสำนัก · 长老 ผู้อาวุโส · 师兄 ศิษย์พี่ · "
        "师妹 ศิษย์น้อง · 师父 อาจารย์.",
        "• Cultivation realms and techniques are translated by meaning, and the same realm is always "
        "written the same way. 剑 is กระบี่ in martial arts.",
    ]),
    "Japanese": "\n".join([
        "NAMES (Japanese → Thai): transliterate the reading (Hepburn) the way Thai manga publishers do — "
        "佐藤 ซาโต้ · 鈴木 ซูซูกิ · 高橋 ทาคาฮาชิ · 翔太 โชตะ · さくら ซากุระ.",
        "• Honorific suffixes (さん/くん/ちゃん/様/先輩) are not part of a name: report 田中, not 田中さん.",
        "• Attacks, ranks and organisations with a meaning are translated by meaning.",
    ]),
    "English": "\n".join([
        "NAMES (English → Thai): transliterate by the Royal Institute's rules — Michael ไมเคิล · "
        "Elizabeth เอลิซาเบท · Alexander อเล็กซานเดอร์ · Charlotte ชาร์ลอตต์.",
        "• Titles are translated: Duke ดยุก · Count เคานต์ · Baron บารอน · Sir เซอร์ · Lord ลอร์ด · "
        "Knight อัศวิน.",
    ]),
}

_GENERIC_NAMING = (
    "NAMES: transliterate names the way a professional {target_lang} publisher of this kind of comic "
    "would, and translate terms that have a meaning (skills, ranks, items, organisations) by meaning."
)

JUNK_RULES = (
    "DO NOT REPORT: real countries, cities and brands (Seoul, Tokyo, Samsung); everyday objects and "
    "food; family or role words used for anyone (mom, teacher, captain) unless this story uses one as "
    "a name or a rank; insults, compliments and exclamations; sound effects; numbers and dates. When "
    "in doubt, leave it out — a missing term costs one retranslation, a junk one is sent with every page."
)


def _canonical(source_lang: str) -> str | None:
    lang = (source_lang or "").lower()
    for name in _THAI_NAMING:
        if name.lower() in lang:
            return name
    return None


_HANGUL = re.compile("[가-힣ᄀ-ᇿ㄰-㆏]")
_KANA = re.compile("[぀-ヿㇰ-ㇿ]")
_HAN = re.compile("[一-鿿㐀-䶿]")
_LATIN = re.compile("[A-Za-z]")


def script_language(text: str) -> str | None:
    """The source language the letters of a text say, or None when they do not say.

    Kana anywhere means Japanese (Japanese mixes kanji in, Chinese never has
    kana); otherwise the largest script wins once it is most of the letters.
    """
    sample = (text or "")[:20000]
    counts = {
        "Korean": len(_HANGUL.findall(sample)),
        "Japanese": len(_KANA.findall(sample)),
        "Chinese": len(_HAN.findall(sample)),
        "English": len(_LATIN.findall(sample)),
    }
    total = sum(counts.values())
    if total < 20:
        return None
    if counts["Japanese"] >= 0.1 * total:
        return "Japanese"
    best = max(counts, key=counts.get)
    return best if counts[best] >= 0.6 * total else None


def rules_language(selected: str, text: str) -> tuple[str, str | None]:
    """The language to give rules for, and the language the text turned out to be
    when that differs from the setting (for a warning), else None."""
    chosen = _canonical(selected)
    seen = script_language(text)
    if seen and seen != chosen:
        return seen, (seen if chosen else None)
    return chosen or selected, None


def extraction_naming_rules(source_lang: str, target_lang: str) -> str:
    """The naming block of the extraction prompt, for this pair of languages."""
    if "thai" in (target_lang or "").lower():
        rules = _THAI_NAMING.get(_canonical(source_lang) or "")
        if rules:
            return rules + "\n" + JUNK_RULES
    return _GENERIC_NAMING.replace("{target_lang}", target_lang or "the target language") + "\n" + JUNK_RULES
