"""Hayai OCR v2.7 Supernova (ONNX, int8): reads a whole text block in one pass.

A ~157M-parameter crop-level reader (SigLIP2 NaFlex encoder + causal decoder) by
JustANormalTinkerer, Apache-2.0. The preprocessing and the greedy decode loop are
adapted from the model repository's ``inference_onnx.py``
(https://huggingface.co/JustANormalTinkerer/hayai-ocr-v2.7-supernova-onnx).

Measured on the three Korean test pages in ``tests/data/webtoon_ko`` (32 blocks,
4-core CPU): Hangul error 0.0% against 10.7% for PP-OCRv5 Korean, 31 of 32 blocks
exact against 6, about the same as gemini-3.1-flash-lite through OpenRouter, at
~0.15 s a block and ~400 MB. On three Japanese manga pages (22 blocks) it misread
2 (a small ぃ as い) where manga-ocr, the Default for Japanese, misread 10 (黄昏 → 黄春,
S級 → ３級, 用済み → 用務み, words it made up). The owner tried it on English and found it
good. It is offered for Korean, English and Japanese.

Two things differ from the reference script:

* The tokenizer is byte-level BPE, so decoding is a table lookup done here rather
  than through the ``tokenizers`` package, which the app does not otherwise need.
* The model has no language hint. With a crop cut tight to the letters it once
  wrote す and 叶 into Korean lines, so every block is cut with ``PAD`` pixels of
  room, and tokens that would begin a character of a script the page's language
  never uses are never chosen (``script_ban``): kana and ideographs for Korean,
  those and Hangul (and CJK punctuation) for English, Hangul for Japanese.
"""
from __future__ import annotations

import json
import logging
import math
import os
from functools import lru_cache

import numpy as np
from PIL import Image

from modules.ocr.base import OCREngine
from modules.utils.download import ModelDownloader, ModelID
from modules.utils.onnx import make_session, make_session_options
from modules.utils.textblock import TextBlock

logger = logging.getLogger(__name__)

PAD = 16  # pixels of room round each block; tighter crops misread (see module doc)
MAX_NEW_TOKENS = 160
PATCH_TIERS = (128, 192, 256, 384)


# --- NaFlex sizing, as in the reference script ---------------------------------

@lru_cache(maxsize=4096)
def naflex_target_size(height: int, width: int, max_patches: int = 256, patch_size: int = 16,
                       min_patches: int = 64, max_scale: float = 4.0) -> tuple[int, int, int, int]:
    """Largest size, in whole patches, that keeps the page's proportions within max_patches."""
    def size_at(scale):
        th = max(patch_size, int(math.ceil(height * scale / patch_size)) * patch_size)
        tw = max(patch_size, int(math.ceil(width * scale / patch_size)) * patch_size)
        return th, tw

    lo, hi = 1e-5, max_scale
    while hi - lo >= 1e-5:
        mid = 0.5 * (lo + hi)
        th, tw = size_at(mid)
        if (th // patch_size) * (tw // patch_size) <= max_patches:
            lo = mid
        else:
            hi = mid
    th, tw = size_at(lo)
    if (th // patch_size) * (tw // patch_size) < min_patches:
        target = min(min_patches, max_patches)
        lo2, hi2 = lo, 100.0
        while hi2 - lo2 >= 1e-5:
            mid = 0.5 * (lo2 + hi2)
            th, tw = size_at(mid)
            if (th // patch_size) * (tw // patch_size) <= target:
                lo2 = mid
            else:
                hi2 = mid
        th, tw = size_at(lo2)
    return th, tw, th // patch_size, tw // patch_size


@lru_cache(maxsize=4096)
def select_max_patches(height: int, width: int, patch_size: int = 16, min_patches: int = 64,
                       max_scale: float = 4.0) -> int:
    """The reference script's 'auto' tier: more patches only where the crop needs them."""
    info = {}
    for mp in PATCH_TIERS:
        th, tw, nh, nw = naflex_target_size(height, width, mp, patch_size, min_patches, max_scale)
        info[mp] = (nh * nw, min(th / max(1, height), tw / max(1, width)))
    n128, s128 = info[128]
    n192, s192 = info[192]
    n256, s256 = info[256]
    n384, _ = info[384]
    if n128 == n384:
        return 128
    h, w = max(1, height), max(1, width)
    aspect = max(h, w) / min(h, w)
    w_over_h = w / h
    square = 0.77 <= w_over_h <= 1.30
    horizontal = w_over_h > 1.30
    if not square:
        if not horizontal and s128 >= 1.65 and aspect < 3.8:
            return 128
        if horizontal and s128 >= 2.35 and aspect < 3.2:
            return 128
    if n384 > n256 and (s256 < 1.28 or (square and s256 < 2.20) or (horizontal and s256 < 1.45)
                        or (aspect >= 3.8 and s256 < 1.75) or (aspect >= 5.0 and s256 < 2.20)):
        return 384
    if n192 == n128:
        return 128
    if n256 == n192:
        return 192
    if not square:
        if not horizontal and s192 >= 1.55 and aspect < 3.6:
            return 192
        if horizontal and s192 >= 1.85 and aspect < 3.0:
            return 192
    return 256


# --- Byte-level BPE --------------------------------------------------------------

def _byte_alphabet() -> dict[str, int]:
    """GPT-2's printable stand-in for each byte, reversed (character -> byte)."""
    printable = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) \
        + list(range(ord("®"), ord("ÿ") + 1))
    chars = printable[:]
    extra = 0
    for b in range(256):
        if b not in printable:
            printable.append(b)
            chars.append(256 + extra)
            extra += 1
    return {chr(c): b for b, c in zip(printable, chars)}


class ByteLevelVocab:
    """Token id -> bytes for a byte-level BPE ``tokenizer.json``."""

    def __init__(self, tokenizer_path: str):
        with open(tokenizer_path, encoding="utf-8") as handle:
            spec = json.load(handle)
        to_byte = _byte_alphabet()
        vocab = spec["model"]["vocab"]
        special = {t["id"] for t in spec.get("added_tokens", []) if t.get("special", True)}
        size = max(max(vocab.values()), max(special, default=0)) + 1
        self.pieces: list[bytes] = [b""] * size
        for token, idx in vocab.items():
            if idx in special:
                continue
            try:
                self.pieces[idx] = bytes(to_byte[c] for c in token)
            except KeyError:  # not a byte-level token; it never forms text
                self.pieces[idx] = b""

    def decode(self, ids) -> str:
        return b"".join(self.pieces[i] for i in ids if 0 <= i < len(self.pieces)).decode("utf-8", "replace")


#: The languages Hayai is offered for, by the code the factory passes.
LANGUAGES = ("ko", "en", "ja")


def _is_kana_or_han_lead(data: bytes, i: int) -> bool:
    """Does a UTF-8 character starting at ``data[i]`` lie in kana or CJK ideographs?"""
    b = data[i]
    if 0xE4 <= b <= 0xE9:  # U+4000..U+9FFF: CJK ideographs (and Yi, which never appears)
        return True
    if b == 0xE3 and i + 1 < len(data) and 0x81 <= data[i + 1] <= 0x83:  # U+3040..U+30FF: kana
        return True
    return b == 0xE3 and 0x90 <= (data[i + 1] if i + 1 < len(data) else 0) <= 0xBF  # U+3400..: ext. A


def _forbidden_at(language: str, data: bytes, i: int) -> bool:
    """Does the character starting at ``data[i]`` belong to a script ``language`` never writes?"""
    b = data[i]
    if language == "ja":
        return 0xEA <= b <= 0xED  # U+A000..U+DFFF: Hangul (and Yi, never used)
    if language == "en":
        # Every lead from U+3000 to U+DFFF: CJK punctuation, kana, ideographs, Hangul.
        # U+2000..U+2FFF (… — ‘ ’ ★ ♥) and full-width forms (U+FFxx) stay allowed.
        return 0xE3 <= b <= 0xED
    return _is_kana_or_han_lead(data, i)  # Korean


def script_ban(pieces: list[bytes], language: str = "ko") -> np.ndarray:
    """Tokens a line in ``language`` never needs: any that starts a character of a script
    that language does not use."""
    ban = np.zeros(len(pieces), dtype=bool)
    for idx, piece in enumerate(pieces):
        if any(_forbidden_at(language, piece, i) for i in range(len(piece))):
            ban[idx] = True
    return ban


def korean_ban(pieces: list[bytes]) -> np.ndarray:
    return script_ban(pieces, "ko")


def _continues_kana(pieces: list[bytes]) -> np.ndarray:
    """Tokens that would turn a trailing lone 0xE3 into kana (first byte 0x81..0x83 or 0x90..0xBF)."""
    return np.array([bool(p) and (0x81 <= p[0] <= 0x83 or 0x90 <= p[0] <= 0xBF) for p in pieces])


class HayaiOCR(OCREngine):
    """Hayai OCR, one block at a time, on the CPU (the int8 graph has no GPU kernels)."""

    def __init__(self):
        self.prefill = None
        self.decode_sess = None
        self.language = "ko"
        self._ban = None
        self._after_e3 = None
        self._pos_cache: dict[tuple[int, int], np.ndarray] = {}

    def initialize(self, language: str = "ko", **_kwargs) -> None:
        if language not in LANGUAGES:
            raise ValueError(f"Hayai is offered for {', '.join(LANGUAGES)}, not {language!r}")
        ModelDownloader.get(ModelID.HAYAI_OCR_ONNX)
        path = lambda name: ModelDownloader.get_file_path(ModelID.HAYAI_OCR_ONNX, name)
        with open(path("hayai_onnx_config.json"), encoding="utf-8") as handle:
            self.meta = json.load(handle)
        self.vocab = ByteLevelVocab(path("tokenizer.json"))
        pos = np.load(path("pos_embedding.npy"))
        side = int(round(pos.shape[0] ** 0.5))
        self.pos_side = side
        self.pos_grid = pos.reshape(side, side, -1).astype(np.float32)
        # The arena off holds ~80 MB less between blocks at no measurable cost.
        options = make_session_options(low_mem=True)
        providers = ["CPUExecutionProvider"]
        self.prefill = make_session(path("hayai_prefill_int8.onnx"), providers=providers, sess_options=options)
        self.decode_sess = make_session(path("hayai_decode_int8.onnx"), providers=providers, sess_options=options)
        self.language = language
        self._ban = None
        self._after_e3 = None

    # -- model plumbing -------------------------------------------------------

    def _pos_embed(self, nh: int, nw: int) -> np.ndarray:
        # A dict on the engine, not lru_cache on the method: that would hold the
        # engine (and its 265 MB of sessions) past the idle model release.
        cached = self._pos_cache.get((nh, nw))
        if cached is not None:
            return cached

        def weights(out_size, in_size):
            scale = in_size / out_size
            inv = 1.0 / scale if scale > 1.0 else 1.0
            centres = scale * (np.arange(out_size, dtype=np.float32) + 0.5)
            j = np.arange(in_size, dtype=np.float32) + 0.5
            w = np.maximum(0.0, 1.0 - np.abs(j[None, :] - centres[:, None]) * inv)
            return w / np.maximum(w.sum(axis=1, keepdims=True), 1e-12)

        value = np.einsum("ih,jw,hwd->ijd", weights(nh, self.pos_side), weights(nw, self.pos_side),
                          self.pos_grid).reshape(nh * nw, -1)
        self._pos_cache[(nh, nw)] = value
        return value

    def _inputs(self, crop: np.ndarray):
        ps, min_p, ms = self.meta["patch_size"], self.meta["min_patches"], self.meta["max_scale"]
        mult = self.meta["pad_to_multiple_of"]
        h, w = crop.shape[:2]
        mp = select_max_patches(h, w, ps, min_p, ms)
        th, tw, nh, nw = naflex_target_size(h, w, mp, ps, min_p, ms)
        image = Image.fromarray(crop)
        if (tw, th) != (w, h):
            image = image.resize((tw, th), resample=Image.Resampling.BILINEAR)
        arr = np.asarray(image, dtype=np.uint8)
        patches = arr.reshape(nh, ps, nw, ps, 3).transpose(0, 2, 1, 3, 4).reshape(nh * nw, ps * ps * 3)
        n = nh * nw
        keep = max(mult, ((n + mult - 1) // mult) * mult)
        pixels = np.zeros((1, keep, ps * ps * 3), np.float32)
        pixels[0, :n] = patches.astype(np.float32) * (2.0 / 255.0) - 1.0
        pos = np.zeros((1, keep, self.pos_grid.shape[-1]), np.float32)
        pos[0, :n] = self._pos_embed(nh, nw)
        l_vis = ((nh + 1) // 2) * ((nw + 1) // 2)
        return {
            "pixel_values": pixels,
            "pos_embeds": pos,
            "spatial_shapes": np.array([[nh, nw]], np.int64),
            "bos_ids": np.array([[self.meta["bos_token_id"]]], np.int64),
            "l_vis_arange": np.arange(l_vis, dtype=np.int64),
        }

    def _bans(self, size: int):
        if self._ban is None or len(self._ban) != size:
            pieces = self.vocab.pieces + [b""] * max(0, size - len(self.vocab.pieces))
            pieces = pieces[:size]
            self._ban = script_ban(pieces, self.language)
            self._after_e3 = _continues_kana(pieces)
        return self._ban, self._after_e3

    def _pick(self, logits: np.ndarray, written: bytes) -> int:
        ban, after_e3 = self._bans(logits.shape[-1])
        logits = np.where(ban, -np.inf, logits)
        # A lone 0xE3 is allowed only for Korean (「」 begin with it); kana may not follow.
        if self.language == "ko" and written.endswith(b"\xe3"):
            logits = np.where(after_e3, -np.inf, logits)
        return int(np.argmax(logits))

    def read(self, crop: np.ndarray) -> str:
        """Read one crop (RGB uint8)."""
        bos, eos, pad = self.meta["bos_token_id"], self.meta["eos_token_id"], self.meta["pad_token_id"]
        logits, k_cache, v_cache, vis_valid = self.prefill.run(None, self._inputs(crop))
        ids: list[int] = []
        written = b""
        token = self._pick(logits[0], written)
        mask = np.concatenate([vis_valid, np.ones((1, 1), np.int64)], axis=1)
        for step in range(1, MAX_NEW_TOKENS + 1):
            if token in (eos, pad):
                break
            if token != bos:
                ids.append(token)
                if token < len(self.vocab.pieces):
                    written = (written + self.vocab.pieces[token])[-4:]
            if step == MAX_NEW_TOKENS:
                break
            logits, k_cache, v_cache = self.decode_sess.run(None, {
                "input_ids": np.array([[token]], np.int64),
                "past_attention_mask": mask,
                "position_id": np.array([step], np.int64),
                "k_cache_in": k_cache,
                "v_cache_in": v_cache,
            })
            mask = np.concatenate([mask, np.ones((1, 1), np.int64)], axis=1)
            token = self._pick(logits[0], written)
        return self.vocab.decode(ids).strip()

    # -- OCREngine ------------------------------------------------------------

    def process_image(self, img: np.ndarray, blk_list: list[TextBlock]) -> list[TextBlock]:
        if img.ndim == 2:
            img = np.repeat(img[..., None], 3, axis=2)
        img = img[..., :3]
        height, width = img.shape[:2]
        for blk in blk_list:
            box = blk.xyxy if blk.xyxy is not None else blk.bubble_xyxy
            if box is None:
                blk.text = ""
                continue
            x1, y1, x2, y2 = (int(v) for v in box)
            x1, y1 = max(0, x1 - PAD), max(0, y1 - PAD)
            x2, y2 = min(width, x2 + PAD), min(height, y2 + PAD)
            if x2 - x1 < 2 or y2 - y1 < 2:
                blk.text = ""
                continue
            try:
                blk.text = self.read(np.ascontiguousarray(img[y1:y2, x1:x2]))
            except Exception:
                logger.exception("Hayai OCR failed on a block")
                blk.text = ""
        return blk_list
