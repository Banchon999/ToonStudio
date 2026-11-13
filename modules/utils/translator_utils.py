import base64
import json
import logging
import re
import numpy as np
from .textblock import TextBlock
import imkit as imk

logger = logging.getLogger(__name__)


MODEL_MAP = {
    "Custom": "",  
    "Deepseek": "deepseek-v4-flash", 
    "GPT-4.1": "gpt-4.1",
    "GPT-4.1-mini": "gpt-4.1-mini",
    "Claude-4.6-Sonnet": "claude-sonnet-4-6",
    "Claude-4.5-Haiku": "claude-haiku-4-5-20251001",
    "Gemini-2.5-Flash-Lite": "gemini-2.5-flash-lite",
    "Gemini-3.1-Flash-Lite": "gemini-3.1-flash-lite",
    "Gemini-2.5-Pro": "gemini-2.5-pro"
}

def encode_image_array(img_array: np.ndarray):
    img_bytes = imk.encode_image(img_array, ".png")
    return base64.b64encode(img_bytes).decode('utf-8')

#: Scripts written without spaces between words: a line break between two of
#: their characters joins them with nothing, anywhere else with a space.
_UNSPACED = re.compile(r"[\u0E00-\u0E7F\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]")
#: Sentence-ending marks after which Thai still takes a space.
_SENTENCE_END = set("!?.…\"')”’»」』）)ฯ")
_LINE_BREAKS = re.compile(r"\s*(?:\r\n|[\r\n\u2028\u2029])\s*")


def join_line_breaks(text: str | None) -> str | None:
    """`text` with its line breaks folded back into running text.

    A bubble's line breaks belong to its layout, not its words, and the
    renderer fits a translation to its bubble itself — it treats every break
    as a forced new line and then wraps each piece again. LLM OCR transcribes
    a bubble line by line, and models (and some traditional translators)
    mirror those breaks in the translation, so a sentence arrived in three
    pieces, each wrapped again into a long line and a stub, and people had to
    delete the breaks by hand. Between two Thai or CJK characters a break
    joins with nothing — which is what deleting it by hand gives — unless a
    sentence ended there; anywhere else with a space.
    """
    if not text or not _LINE_BREAKS.search(text):
        return text
    pieces = [piece for piece in _LINE_BREAKS.split(text.strip()) if piece]
    if not pieces:
        return ""
    joined = pieces[0]
    for piece in pieces[1:]:
        left, right = joined[-1], piece[0]
        unspaced = _UNSPACED.match(left) and _UNSPACED.match(right)
        joined += ("" if unspaced and left not in _SENTENCE_END else " ") + piece
    return joined


def join_translation_line_breaks(blk_list: list[TextBlock]) -> None:
    """join_line_breaks over every block's translation, in place."""
    for blk in blk_list or []:
        translation = getattr(blk, "translation", None)
        if isinstance(translation, str):
            blk.translation = join_line_breaks(translation)


def get_raw_text(blk_list: list[TextBlock]):
    rw_txts_dict = {}
    for idx, blk in enumerate(blk_list):
        block_key = f"block_{idx}"
        # Sent without its line breaks: a model handed a bubble line by line
        # answers line by line (see join_line_breaks).
        rw_txts_dict[block_key] = join_line_breaks(blk.text)
    
    raw_texts_json = json.dumps(rw_txts_dict, ensure_ascii=False, indent=4)
    
    return raw_texts_json

def get_raw_translation(blk_list: list[TextBlock]):
    rw_translations_dict = {}
    for idx, blk in enumerate(blk_list):
        block_key = f"block_{idx}"
        rw_translations_dict[block_key] = blk.translation
    
    raw_translations_json = json.dumps(rw_translations_dict, ensure_ascii=False, indent=4)
    
    return raw_translations_json

_GENDERS = {
    "male": "male", "m": "male", "man": "male", "boy": "male", "ชาย": "male",
    "female": "female", "f": "female", "woman": "female", "girl": "female", "หญิง": "female",
}


def normalise_gender(value) -> str:
    """"male", "female", or "" for anything else (unknown, neutral, missing)."""
    return _GENDERS.get(str(value or "").strip().lower(), "")


class ReplyParseError(ValueError):
    """The model's reply held no translation the app could read."""


_FENCE = re.compile(r"```(?:json)?\s*|```", re.IGNORECASE)
_BLOCK_KEY = re.compile(r'"(block_\d+)"\s*:\s*')


def _repair_json(text: str) -> str:
    """The reply with the faults models make in JSON mended.

    Both faults that give "Expecting ',' delimiter" are handled: a double
    quote inside a string is escaped unless what follows it can end a string
    (``, : } ]``, the end, or a new line starting the next key) — models
    quote speech inside a translation (เขาพูดว่า "ไป") without escaping it —
    and a comma missing between two fields on separate lines is put back.
    A raw line break inside a string becomes ``\\n``, and a comma before
    ``}`` or ``]`` is dropped.
    """
    out = []
    in_string = False
    escaped = False
    length = len(text)
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
                out.append(ch)
            elif ch == "\\":
                escaped = True
                out.append(ch)
            elif ch == '"':
                j = i + 1
                while j < length and text[j] in " \t\r\n":
                    j += 1
                if j >= length or text[j] in ",:}]":
                    in_string = False
                    out.append(ch)
                elif text[j] == '"' and "\n" in text[i + 1:j]:
                    # The next key on a new line: the string ended and the
                    # comma between the fields is missing.
                    in_string = False
                    out.append('",')
                else:
                    out.append('\\"')
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                continue
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
                out.append(ch)
            elif ch == ",":
                j = i + 1
                while j < length and text[j] in " \t\r\n":
                    j += 1
                if j < length and text[j] in "}]":
                    continue
                out.append(ch)
            elif ch in "}]":
                out.append(ch)
                j = i + 1
                while j < length and text[j] in " \t\r\n":
                    j += 1
                if j < length and text[j] in '"{' and "\n" in text[i + 1:j]:
                    out.append(",")   # a missing comma between two values
            else:
                out.append(ch)
    return "".join(out)


def _unquote(raw: str) -> str:
    try:
        return json.loads('"' + raw + '"')
    except json.JSONDecodeError:
        return raw.replace('\\"', '"').replace("\\n", "\n")


def _salvage_blocks(text: str) -> dict:
    """Each block's value read on its own, when the reply as a whole is not
    JSON even after repair: one broken bubble then costs that bubble at most,
    not the page."""
    keys = list(_BLOCK_KEY.finditer(text))
    found: dict = {}
    for n, key in enumerate(keys):
        segment = text[key.end(): keys[n + 1].start() if n + 1 < len(keys) else len(text)]
        segment = segment.rstrip().rstrip(",}").rstrip()
        if segment.startswith("{"):
            value = {}
            for field in ("speaker", "gender", "mode"):
                m = re.search(r'"%s"\s*:\s*"([^"]*)"' % field, segment)
                if m:
                    value[field] = m.group(1)
            m = re.search(r'"translation"\s*:\s*"', segment)
            if not m:
                continue
            rest = segment[m.end():]
            # The translation runs to the quote that ends the field: the one
            # before another field's name, or else the last one.
            nxt = re.search(r'"\s*,\s*"(?:speaker|gender|mode|text)"\s*:', rest)
            end = nxt.start() if nxt else rest.rfind('"')
            if end < 0:
                continue
            value["translation"] = _unquote(rest[:end])
            found[key.group(1)] = value
        elif segment.startswith('"'):
            end = segment.rfind('"')
            if end <= 0:
                continue
            found[key.group(1)] = _unquote(segment[1:end])
    return found


def parse_reply_json(reply: str) -> dict:
    """The block → translation object in a model's reply, as tolerantly as
    the reply allows; raises ReplyParseError when nothing can be read.

    In order: the first JSON object as written (text before or after it, a
    code fence, braces in a closing remark all ignored); the same object
    with `_repair_json`'s mends; and finally `_salvage_blocks`, block by
    block.
    """
    text = _FENCE.sub("", reply or "")
    start = text.find("{")
    if start < 0:
        raise ReplyParseError("the reply contains no JSON object")
    text = text[start:]
    decoder = json.JSONDecoder()
    error = None
    for candidate in (text, _repair_json(text)):
        try:
            value, _end = decoder.raw_decode(candidate)
        except json.JSONDecodeError as exc:
            error = error or exc
            continue
        if isinstance(value, dict):
            return value
    salvaged = _salvage_blocks(text)
    if salvaged:
        logger.warning("Translation reply was not valid JSON (%s); read %d block(s) one by one",
                       error, len(salvaged))
        return salvaged
    raise ReplyParseError(str(error) if error else "the reply could not be read")


def set_texts_from_json(blk_list: list[TextBlock], json_string: str):
    """Fill each block's translation from the model's JSON reply.

    A value is either the translation itself or, when the model was asked who
    speaks each block (translating into Thai), an object
    {"speaker": ..., "gender": ..., "translation": ...}. Both are accepted
    whatever was asked for: a model that answers in the plain shape still
    gets its translation used, it just reports no speaker.
    """
    translation_dict = parse_reply_json(json_string)
    if translation_dict:
        for idx, blk in enumerate(blk_list):
            block_key = f"block_{idx}"
            if block_key in translation_dict:
                value = translation_dict[block_key]
                if isinstance(value, dict):
                    text = value.get("translation", value.get("text", ""))
                    blk.translation = text if isinstance(text, str) else str(text or "")
                    blk.speaker = " ".join(str(value.get("speaker") or "").split())
                    blk.speaker_gender = normalise_gender(value.get("gender"))
                else:
                    blk.translation = value if isinstance(value, str) else str(value)
                    blk.speaker = ""
                    blk.speaker_gender = ""
            else:
                print(f"Warning: {block_key} not found in JSON string.")
    else:
        print("No JSON found in the input string.")

def speakers_so_far(blk_list) -> str:
    """The speakers already named in blk_list, as a line for the next request.

    "" when no block names one. Narration and sound effects are left out.
    """
    seen: dict[str, str] = {}
    for blk in blk_list or []:
        name = getattr(blk, "speaker", "") or ""
        # "???" and the like: a model's way of saying it could not tell.
        if not re.search(r"\w", name) or name.lower() in ("narration", "sfx", "unknown"):
            continue
        gender = getattr(blk, "speaker_gender", "") or ""
        if name not in seen or (gender and not seen[name]):
            seen[name] = gender
    if not seen:
        return ""
    names = ", ".join(f"{n} ({g})" if g else n for n, g in seen.items())
    return (
        "Speakers already identified earlier in this strip — keep the same names and "
        f"genders for them: {names}"
    )


def previous_lines(blk_list, count: int = 6) -> str:
    """The last lines of the conversation before this request, with who said them.

    Names alone were not enough on a real model: a request starting mid-scene
    gave each of its first lines to the speaker of the line before it. "" when
    there is nothing before.
    """
    lines = []
    for blk in list(blk_list or [])[-count:]:
        text = " ".join(str(getattr(blk, "text", "") or "").split())
        if not text:
            continue
        speaker = getattr(blk, "speaker", "") or "unknown"
        lines.append(f"- {speaker}: {text}")
    if not lines:
        return ""
    return (
        "The lines just before these in the strip (already translated — context only, do not "
        "translate them again):\n" + "\n".join(lines)
    )


def set_upper_case(blk_list: list[TextBlock], upper_case: bool):
    for blk in blk_list:
        translation = blk.translation
        if translation is None:
            continue
        if upper_case and not translation.isupper():
            blk.translation = translation.upper() 
        elif not upper_case and translation.isupper():
            blk.translation = translation.lower().capitalize()
        else:
            blk.translation = translation

def format_translations(blk_list: list[TextBlock], trg_lng_cd: str, upper_case: bool = True):
    for blk in blk_list:
        translation = blk.translation
        if translation is None:
            continue
        if upper_case and not translation.isupper():
            blk.translation = translation.upper()
        elif not upper_case and translation.isupper():
            blk.translation = translation.lower().capitalize()
        else:
            blk.translation = translation

def is_there_text(blk_list: list[TextBlock]) -> bool:
    return any(blk.text for blk in blk_list)

def is_renderable_translation(translation: str | None) -> bool:
    """True if the render stage should draw this translation.

    Punctuation-only translations (an echoed "?", "!?", "...") aren't worth
    redrawing — the original artwork already shows the same thing. Anything
    gated on rendering (like inpainting) must skip them too, otherwise the
    bubble gets cleaned with nothing drawn over it. Unlike a length check,
    this keeps legitimate single-character translations (e.g. "何", "5").
    """
    if not translation:
        return False
    return any(ch.isalnum() for ch in translation)
