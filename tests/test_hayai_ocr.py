"""Hayai OCR: a Korean-only OCR choice (modules/ocr/hayai_ocr.py).

Measured on tests/data/webtoon_ko (32 detected blocks): Hangul error 0.0% and 31/32
blocks exact, against 10.7% and 6/32 for PP-OCRv5 Korean, at ~0.15 s a block on a
4-core CPU. The real-model test at the bottom runs only where the model is downloaded.
"""
import json
import os

import numpy as np
import pytest

from modules.ocr import hayai_ocr as H


def _byte_token(text: str) -> str:
    """Write ``text`` the way a byte-level BPE vocabulary stores it."""
    to_char = {b: c for c, b in H._byte_alphabet().items()}
    return "".join(to_char[b] for b in text.encode("utf-8"))


@pytest.fixture
def vocab(tmp_path):
    words = ["[PAD]", "[UNK]", "[BOS]", "[EOS]", "탑", "?", "...", " 이", "「", "」", "す", "叶", "HP", "あ"[:1]]
    spec = {
        "model": {"type": "BPE", "vocab": {(_byte_token(w) if i >= 4 else w): i for i, w in enumerate(words)}},
        "added_tokens": [{"id": i, "content": w, "special": True} for i, w in enumerate(words[:4])],
    }
    path = tmp_path / "tokenizer.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return H.ByteLevelVocab(str(path)), words


class TestDecoding:
    def test_byte_level_tokens_decode_to_text(self, vocab):
        v, _ = vocab
        assert v.decode([6, 7, 4, 5]) == "... 이탑?"

    def test_special_tokens_write_nothing(self, vocab):
        v, _ = vocab
        assert v.decode([2, 4, 3, 0]) == "탑"

    def test_a_character_split_across_tokens_is_joined(self, tmp_path):
        raw = "탑".encode("utf-8")
        to_char = {b: c for c, b in H._byte_alphabet().items()}
        vocab = {to_char[raw[0]]: 0, "".join(to_char[b] for b in raw[1:]): 1}
        path = tmp_path / "tokenizer.json"
        path.write_text(json.dumps({"model": {"vocab": vocab}}), encoding="utf-8")
        assert H.ByteLevelVocab(str(path)).decode([0, 1]) == "탑"


class TestScriptsALanguageNeverWrites:
    def test_korean_never_chooses_kana_or_ideographs(self, vocab):
        v, words = vocab
        banned = {words[i] for i in np.flatnonzero(H.script_ban(v.pieces, "ko"))}
        assert {"す", "叶", "あ"} <= banned
        for word in ("탑", "?", "...", " 이", "「", "」", "HP"):
            assert word not in banned, word

    def test_english_never_chooses_cjk_or_hangul(self, vocab):
        v, words = vocab
        banned = {words[i] for i in np.flatnonzero(H.script_ban(v.pieces, "en"))}
        assert {"す", "叶", "あ", "탑", " 이", "「", "」"} <= banned
        for word in ("?", "...", "HP"):
            assert word not in banned, word

    def test_english_keeps_its_own_punctuation(self):
        pieces = ["…".encode(), "—".encode(), "’".encode(), "♥".encode(), "！".encode()]
        assert not H.script_ban(pieces, "en").any(), "U+2000..U+2FFF and full-width forms stay"

    def test_japanese_never_chooses_hangul(self, vocab):
        v, words = vocab
        banned = {words[i] for i in np.flatnonzero(H.script_ban(v.pieces, "ja"))}
        assert {"탑", " 이"} <= banned
        for word in ("す", "叶", "あ", "「", "」", "?", "HP"):
            assert word not in banned, word

    def test_a_lone_lead_byte_cannot_become_kana_in_korean(self):
        engine = H.HayaiOCR()
        engine.language = "ko"
        engine.vocab = type("V", (), {"pieces": [b"\x81\x82", b"\x80\x8c", b"a"]})()
        logits = np.array([5.0, 1.0, 0.0])
        assert engine._pick(logits, b"\xe3") == 1, "「 (E3 80 8C) may follow, あ (E3 81 82) may not"
        assert engine._pick(logits, b"x") == 0

    def test_japanese_may_write_kana(self):
        engine = H.HayaiOCR()
        engine.language = "ja"
        engine.vocab = type("V", (), {"pieces": ["す".encode(), "탑".encode()]})()
        assert engine._pick(np.array([3.0, 1.0]), b"") == 0
        assert engine._pick(np.array([1.0, 3.0]), b"") == 0, "Hangul never, even when likelier"

    def test_an_unoffered_language_is_refused(self):
        with pytest.raises(ValueError):
            H.HayaiOCR().initialize(language="zh")


def test_naflex_sizes_stay_in_whole_patches_within_the_budget():
    for h, w in ((40, 300), (300, 40), (120, 120), (900, 200), (8, 8)):
        mp = H.select_max_patches(h, w)
        assert mp in H.PATCH_TIERS
        th, tw, nh, nw = H.naflex_target_size(h, w, mp)
        assert th % 16 == 0 and tw % 16 == 0 and nh * nw <= max(mp, 64)


def test_blocks_are_read_with_room_round_them_and_clipped_to_the_page():
    from modules.utils.textblock import TextBlock

    engine = H.HayaiOCR()
    seen = []
    engine.read = lambda crop: seen.append(crop.shape) or "탑"
    img = np.zeros((200, 300, 3), np.uint8)
    blocks = [TextBlock(text_bbox=np.array([50, 60, 100, 90])), TextBlock(text_bbox=np.array([0, 0, 10, 10]))]
    engine.process_image(img, blocks)
    assert seen[0] == (30 + 2 * H.PAD, 50 + 2 * H.PAD, 3)
    assert seen[1] == (10 + H.PAD, 10 + H.PAD, 3)
    assert [b.text for b in blocks] == ["탑", "탑"]


def test_a_block_that_fails_is_left_empty_not_fatal():
    from modules.utils.textblock import TextBlock

    engine = H.HayaiOCR()

    def boom(crop):
        raise RuntimeError("onnx")

    engine.read = boom
    blocks = [TextBlock(text_bbox=np.array([5, 5, 50, 50]), text="old")]
    engine.process_image(np.zeros((80, 80, 3), np.uint8), blocks)
    assert blocks[0].text == ""


class TestChoosingIt:
    @pytest.fixture
    def factory(self, monkeypatch):
        from modules.ocr.factory import OCRFactory

        made = []
        monkeypatch.setattr(OCRFactory, "_engines", {})
        monkeypatch.setattr(OCRFactory, "_create_hayai_ocr",
                            staticmethod(lambda s, lang: made.append(("hayai", lang)) or ("hayai", lang)))
        monkeypatch.setattr(OCRFactory, "_create_ppocr", staticmethod(lambda s, lang, *a, **k: made.append(lang) or lang))
        monkeypatch.setattr(OCRFactory, "_create_manga_ocr", staticmethod(lambda s, *a: made.append("manga") or "manga"))
        settings = type("S", (), {"get_credentials": lambda s, k: {}, "is_gpu_enabled": lambda s: False})()
        return OCRFactory, settings, made

    @pytest.mark.parametrize("language, code", [("Korean", "ko"), ("korean", "ko"), ("English", "en"),
                                                ("latin", "en"), ("Japanese", "ja"), ("japanese", "ja")])
    @pytest.mark.parametrize("name", ["Hayai", "Hayai (Korean)"])
    def test_korean_english_and_japanese_are_read_by_hayai(self, factory, language, code, name):
        f, settings, made = factory
        assert f.create_engine(settings, language, name) == ("hayai", code)

    @pytest.mark.parametrize("language, default", [("Chinese", "ch"), ("chinese", "ch"), ("Russian", "ru")])
    def test_other_languages_get_their_default_engine(self, factory, language, default):
        f, settings, made = factory
        assert f.create_engine(settings, language, "Hayai") == default
        assert not any(isinstance(m, tuple) for m in made)

    def test_settings_list_it_and_map_it(self, qapp):
        from app.ui.settings.settings_ui import SettingsPageUI

        ui = SettingsPageUI()
        assert "Hayai" in ui.ocr_engines and "Hayai (Korean)" not in ui.ocr_engines
        assert ui.value_mappings["Hayai"] == "Hayai"
        combo = ui.tools_page.ocr_combo if hasattr(ui, "tools_page") else None
        if combo is not None:
            from PySide6 import QtCore

            tip = combo.itemData(combo.findText("Hayai"), QtCore.Qt.ItemDataRole.ToolTipRole)
            assert tip and "Korean, English and Japanese" in tip

    def test_a_setting_saved_under_the_old_name_still_picks_it(self, qapp):
        from PySide6.QtCore import QSettings

        from app.ui.settings.settings_page import SettingsPage

        store = QSettings("ComicLabs", "ComicTranslate")
        store.beginGroup("tools"); store.setValue("ocr", "Hayai (Korean)"); store.endGroup()
        page = SettingsPage()
        page.load_settings()
        assert page.ui.ocr_combo.currentText() == "Hayai"
        store.remove("tools/ocr")


def test_the_model_files_are_pinned():
    from modules.utils.download import ModelDownloader, ModelID

    spec = ModelDownloader.registry[ModelID.HAYAI_OCR_ONNX]
    assert "/resolve/bc1e39f9" in spec.url, "a commit, not main: the repository's files are replaced in place"
    assert len(spec.files) == len(spec.sha256) == 5
    assert all(len(h) == 64 for h in spec.sha256)


def _model_here():
    from modules.utils.download import ModelDownloader, ModelID

    spec = ModelDownloader.registry[ModelID.HAYAI_OCR_ONNX]
    return all(os.path.exists(os.path.join(spec.save_dir, f)) for f in spec.files)


@pytest.mark.skipif(not _model_here(), reason="Hayai's files are not downloaded here")
def test_real_model_reads_the_korean_test_pages():
    from PIL import Image

    from modules.utils.textblock import TextBlock

    engine = H.HayaiOCR()
    engine.initialize(language="ko")
    root = os.path.join(os.path.dirname(__file__), "data", "webtoon_ko")
    cases = [  # boxes RT-DETR-v2 found; PP-OCRv5 read the first as "탄2 리?"
        ("page_01.png", [704, 622, 801, 679], "...탑?"),
        ("page_02.png", [249, 1290, 596, 1385], "당신을 '탑'에 입장시킵니다. -준비가 완료되었습니다."),
        ("page_03.png", [638, 576, 753, 683], "설마... 그 유명한「탑」인가?"),
    ]
    for name, box, expected in cases:
        img = np.asarray(Image.open(os.path.join(root, name)).convert("RGB"))
        blk = TextBlock(text_bbox=np.array(box))
        engine.process_image(img, [blk])
        # Spacing round a dash varies with the ONNX Runtime build; the letters may not.
        assert blk.text.replace(" ", "") == expected.replace(" ", ""), (name, blk.text)


@pytest.mark.skipif(not _model_here(), reason="Hayai's files are not downloaded here")
def test_real_model_reads_english_lettering():
    from PIL import Image

    from modules.utils.textblock import TextBlock

    engine = H.HayaiOCR()
    engine.initialize(language="en")
    page = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "images", "demo", "page.png")
    img = np.asarray(Image.open(page).convert("RGB"))
    for box, expected in (([103, 545, 275, 665], "TO THE OLD LIGHTHOUSE, MINA."),
                          ([613, 261, 840, 357], "WHERE ARE WE GOING, JUN?")):
        blk = TextBlock(text_bbox=np.array(box))
        engine.process_image(img, [blk])
        assert blk.text == expected
