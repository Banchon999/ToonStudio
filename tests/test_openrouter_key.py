"""Models that run on the OpenRouter key, and what happens without one.

Reported as "401 Client Error: Unauthorized ... Missing Authentication
header": the request went out with an empty key field. Two things made that
easy to reach. The key only survives a restart when Save Keys is ticked, and
the named models (GPT-4.1, Gemini-3.1-Flash-Lite — the default translator —
Claude, Deepseek, and Gemini OCR) had run on the hosted account's credit;
once that was removed they had direct engines and nowhere to put a key.
They now run on the OpenRouter key, and nothing is sent without one.
"""

import types

import numpy as np
import pytest

from modules.ocr.factory import OCRFactory
from modules.ocr.openrouter_ocr import OpenRouterOCR
from modules.translation.factory import TranslationFactory
from modules.translation.llm.openrouter import OpenRouterTranslation
from modules.utils.openrouter_models import NAMED_MODELS, uses_openrouter


def settings(api_key="sk-or-test", model="openai/gpt-4o", ocr_model=""):
    creds = {"api_key": api_key, "model": model, "ocr_model": ocr_model}
    asked = []

    def get_credentials(service=""):
        asked.append(service)
        return creds if service == "OpenRouter" else {"save_key": True}

    return types.SimpleNamespace(
        ui=types.SimpleNamespace(tr=lambda s: s),
        get_credentials=get_credentials,
        get_llm_settings=lambda: {"image_input_enabled": True, "extra_context": ""},
        is_gpu_enabled=lambda: False,
        asked=asked,
        creds=creds,
    )


class Captured:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers=None, data=None, **kw):
        import json
        self.calls.append({"url": url, "headers": headers, "payload": json.loads(data)})
        body = {"choices": [{"message": {"content": '{"block_0": "แปลแล้ว"}'}}]}
        return types.SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: body)


@pytest.fixture
def post(monkeypatch):
    captured = Captured()
    monkeypatch.setattr("modules.translation.llm.gpt.requests.post", captured)
    monkeypatch.setattr("modules.ocr.gpt_ocr.requests.post", captured)
    return captured


@pytest.fixture(autouse=True)
def fresh_factories():
    TranslationFactory._engines.clear()
    OCRFactory._engines.clear()
    yield
    TranslationFactory._engines.clear()
    OCRFactory._engines.clear()


class TestNamedModelsRunOnTheOpenRouterKey:
    @pytest.mark.parametrize("name", sorted(set(NAMED_MODELS) - {"Gemini-2.5-Flash-Lite"}))
    def test_every_named_translator_posts_to_openrouter_with_its_id(self, name, post):
        engine = TranslationFactory.create_engine(settings(), "Korean", "Thai", name)
        assert isinstance(engine, OpenRouterTranslation)
        engine._perform_translation("text", "system", np.zeros((8, 8, 3), np.uint8))
        call = post.calls[0]
        assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
        assert call["headers"]["Authorization"] == "Bearer sk-or-test"
        assert call["payload"]["model"] == NAMED_MODELS[name]

    def test_the_text_only_model_is_not_sent_the_page(self, post):
        engine = TranslationFactory.create_engine(settings(), "Korean", "Thai", "Deepseek")
        engine._perform_translation("text", "system", np.zeros((8, 8, 3), np.uint8))
        assert all(isinstance(m["content"], str) or all(p["type"] == "text" for p in m["content"])
                   for m in post.calls[0]["payload"]["messages"])

    def test_openrouter_itself_still_uses_the_typed_model(self, post):
        engine = TranslationFactory.create_engine(settings(), "Korean", "Thai", "OpenRouter")
        engine._perform_translation("text", "system", np.zeros((8, 8, 3), np.uint8))
        assert post.calls[0]["payload"]["model"] == "openai/gpt-4o"

    def test_gemini_ocr_runs_on_the_openrouter_key(self):
        engine = OCRFactory.create_engine(settings(), "Korean", "Gemini-2.5-Flash-Lite")
        assert isinstance(engine, OpenRouterOCR)
        assert engine.model == "google/gemini-2.5-flash-lite"
        assert engine.api_key == "sk-or-test"

    def test_changing_the_key_makes_a_new_engine(self):
        s = settings()
        first = TranslationFactory.create_engine(s, "Korean", "Thai", "GPT-4.1")
        s.creds["api_key"] = "sk-or-other"
        second = TranslationFactory.create_engine(s, "Korean", "Thai", "GPT-4.1")
        assert second is not first and second.api_key == "sk-or-other"

    def test_uses_openrouter(self):
        assert uses_openrouter("OpenRouter") and uses_openrouter("GPT-4.1")
        assert not uses_openrouter("Custom") and not uses_openrouter("DeepL")


class TestNoKeyNoRequest:
    def test_translation_without_a_key_says_where_it_goes(self, post):
        engine = TranslationFactory.create_engine(settings(api_key=""), "Korean", "Thai", "OpenRouter")
        with pytest.raises(RuntimeError, match="Save Keys"):
            engine._perform_translation("text", "system", np.zeros((8, 8, 3), np.uint8))
        assert post.calls == []

    def test_a_key_of_only_spaces_is_no_key(self, post):
        engine = TranslationFactory.create_engine(settings(api_key="  \n"), "Korean", "Thai", "GPT-4.1")
        with pytest.raises(RuntimeError, match="OpenRouter API key"):
            engine._perform_translation("text", "system", np.zeros((8, 8, 3), np.uint8))
        assert post.calls == []

    def test_a_pasted_key_loses_its_whitespace(self, post):
        engine = TranslationFactory.create_engine(settings(api_key=" sk-or-test\n"), "Korean", "Thai", "OpenRouter")
        engine._perform_translation("text", "system", np.zeros((8, 8, 3), np.uint8))
        assert post.calls[0]["headers"]["Authorization"] == "Bearer sk-or-test"

    def test_ocr_without_a_key_says_where_it_goes(self, post):
        engine = OCRFactory.create_engine(settings(api_key=""), "Korean", "Gemini-2.5-Flash-Lite")
        with pytest.raises(ValueError, match="Save Keys"):
            engine._get_gpt_ocr("Zm9v")
        assert post.calls == []


class TestValidation:
    """The run is refused up front, with the message, before anything is sent."""

    @pytest.fixture
    def main(self, qapp, monkeypatch):
        from app import validation
        from app.ui.settings.settings_page import SettingsPage

        page = SettingsPage()
        shown = []
        monkeypatch.setattr(validation.Messages, "show_openrouter_key_missing_error",
                            lambda parent: shown.append("key"))
        main = types.SimpleNamespace(settings_page=page, shown=shown)
        yield main
        page.deleteLater()

    def _select(self, page, translator=None, ocr=None):
        if translator:
            page.ui.translator_combo.setCurrentText(translator)
        if ocr:
            page.ui.ocr_combo.setCurrentText(ocr)

    def test_a_named_translator_without_a_key_is_refused(self, main):
        from app.validation import validate_translator

        self._select(main.settings_page, translator="Gemini-3.1-Flash-Lite")
        main.settings_page.ui.credential_widgets["OpenRouter_api_key"].setText("")
        assert validate_translator(main, "Thai") is False
        assert main.shown == ["key"]

    def test_with_a_key_it_runs(self, main):
        from app.validation import validate_translator

        self._select(main.settings_page, translator="OpenRouter")
        main.settings_page.ui.credential_widgets["OpenRouter_api_key"].setText("sk-or-test")
        assert validate_translator(main, "Thai") is True
        assert main.shown == []

    def test_openrouter_ocr_without_a_key_is_refused(self, main):
        from app.validation import validate_ocr

        self._select(main.settings_page, ocr="OpenRouter")
        main.settings_page.ui.credential_widgets["OpenRouter_api_key"].setText("   ")
        assert validate_ocr(main) is False
        assert main.shown == ["key"]

    def test_local_ocr_needs_no_key(self, main):
        from app.validation import validate_ocr

        self._select(main.settings_page, ocr="PaddleOCR")
        main.settings_page.ui.credential_widgets["OpenRouter_api_key"].setText("")
        assert validate_ocr(main) is True
