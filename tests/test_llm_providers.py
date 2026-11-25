"""Translation on a provider's own key (modules/utils/llm_providers).

The owner asked for the main AI companies as translators of their own —
OpenAI, Anthropic, Google, DeepSeek, xAI, Mistral, Groq, Together — each with
its key and a model of the user's choosing, beside OpenRouter and Custom.
"""

import json
import types

import numpy as np
import pytest

from modules.translation.factory import TranslationFactory
from modules.translation.llm.provider import (
    AnthropicProviderTranslation, GeminiProviderTranslation, ProviderTranslation,
)
from modules.translation.llm.gemini import thinking_config
from modules.utils.llm_providers import (
    ANTHROPIC, GEMINI, PROVIDERS, credential_fields, parse_model_list, provider,
)

PAGE = np.zeros((8, 8, 3), np.uint8)
EXPECTED_CLASS = {
    "openai": ProviderTranslation,
    ANTHROPIC: AnthropicProviderTranslation,
    GEMINI: GeminiProviderTranslation,
}


def settings(name, api_key="key-123", model=""):
    creds = {"api_key": api_key, "model": model}
    return types.SimpleNamespace(
        ui=types.SimpleNamespace(tr=lambda s: s),
        get_credentials=lambda service="": creds if service == name else {"save_key": True},
        get_llm_settings=lambda: {"image_input_enabled": True, "extra_context": ""},
        creds=creds,
    )


class Post:
    """Stands in for requests.post in all three engines' modules."""

    def __init__(self, refuse_images=None):
        self.calls = []
        self.refuse_images = refuse_images  # the status a refusal comes with

    def __call__(self, url, headers=None, data=None, json=None, **kw):
        payload = json if json is not None else _json.loads(data)
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        if self.refuse_images and "image_url" in _json.dumps(payload):
            body = {"error": {"message": "No endpoints found that support image input"}}
            return types.SimpleNamespace(status_code=self.refuse_images, text=_json.dumps(body), json=lambda: body,
                                         headers={}, reason="Bad Request")
        if "anthropic" in url:
            body = {"content": [{"type": "text", "text": "ok"}]}
        elif "generativelanguage" in url:
            body = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        else:
            body = {"choices": [{"message": {"content": "ok"}}]}
        return types.SimpleNamespace(status_code=200, json=lambda: body, text="", headers={})


_json = json


@pytest.fixture
def post(monkeypatch):
    p = Post()
    for mod in ("gpt", "claude", "gemini"):
        monkeypatch.setattr(f"modules.translation.llm.{mod}.requests.post", p)
    return p


@pytest.fixture(autouse=True)
def fresh_factory():
    TranslationFactory._engines.clear()
    yield
    TranslationFactory._engines.clear()


@pytest.mark.parametrize("prov", PROVIDERS, ids=lambda p: p.name)
class TestEveryProvider:
    def test_it_posts_to_its_own_api_with_its_key_and_the_chosen_model(self, prov, post):
        engine = TranslationFactory.create_engine(settings(prov.name, model="my-model"), "Korean", "Thai", prov.name)
        assert type(engine) is EXPECTED_CLASS[prov.protocol]
        assert engine._perform_translation("text", "system", PAGE) == "ok"
        call = post.calls[0]
        assert call["url"].startswith(prov.base_url)
        sent_key = call["headers"].get("Authorization") or call["headers"].get("x-api-key") \
            or call["headers"].get("x-goog-api-key")
        assert sent_key in ("Bearer key-123", "key-123")
        assert "key-123" not in call["url"]  # never in a URL an error could quote
        model = call["payload"].get("model") or call["url"].split("/models/")[1].split(":")[0]
        assert model == "my-model"

    def test_an_empty_model_field_means_the_default_model(self, prov, post):
        engine = TranslationFactory.create_engine(settings(prov.name, model="  "), "Korean", "Thai", prov.name)
        assert engine.model == prov.default_model

    def test_nothing_is_sent_without_a_key_and_the_error_says_where_it_goes(self, prov, post):
        engine = TranslationFactory.create_engine(settings(prov.name, api_key=" \n"), "Korean", "Thai", prov.name)
        with pytest.raises(RuntimeError, match=f"Settings > Advanced > {prov.name}"):
            engine._perform_translation("text", "system", PAGE)
        assert post.calls == []

    def test_it_stores_a_key_and_a_model(self, prov):
        assert credential_fields(prov.name) == ("api_key", "model")


def test_a_new_model_choice_makes_a_new_engine():
    s = settings("OpenAI API", model="gpt-4.1")
    first = TranslationFactory.create_engine(s, "Korean", "Thai", "OpenAI API")
    s.creds["model"] = "gpt-5"
    assert TranslationFactory.create_engine(s, "Korean", "Thai", "OpenAI API") is not first


def test_openai_gets_its_renamed_token_parameter_and_the_rest_the_old_one(post):
    for name, param in (("OpenAI API", "max_completion_tokens"), ("Mistral API", "max_tokens")):
        TranslationFactory.create_engine(settings(name), "Korean", "Thai", name)._perform_translation("t", "s", PAGE)
        assert param in post.calls[-1]["payload"]


def test_deepseek_is_never_sent_the_page(post):
    engine = TranslationFactory.create_engine(settings("DeepSeek API"), "Korean", "Thai", "DeepSeek API")
    engine._perform_translation("text", "system", PAGE)
    assert "image_url" not in json.dumps(post.calls[0]["payload"])


# 400 from the providers themselves; 404 is what OpenRouter answered for
# deepseek/deepseek-chat (measured), which lost the speaker map before.
@pytest.mark.parametrize("status", [400, 404, 422])
def test_a_model_that_refuses_images_is_asked_again_without_and_not_sent_one_again(monkeypatch, status):
    p = Post(refuse_images=status)
    monkeypatch.setattr("modules.translation.llm.gpt.requests.post", p)
    engine = TranslationFactory.create_engine(settings("Groq API"), "Korean", "Thai", "Groq API")
    assert engine._perform_translation("text", "system", PAGE) == "ok"
    assert engine._perform_translation("text", "system", PAGE) == "ok"
    with_image = ["image_url" in json.dumps(c["payload"]) for c in p.calls]
    assert with_image == [True, False, False]


def test_gemini_thinking_is_set_only_the_way_each_generation_takes_it():
    assert thinking_config("gemini-3.1-flash-lite") == {"thinkingLevel": "minimal"}
    assert thinking_config("gemini-3-pro") == {"thinkingLevel": "low"}
    assert thinking_config("gemini-2.5-flash") == {"thinkingBudget": 0}
    # 2.5 Pro refuses both a level and a zero budget
    assert thinking_config("gemini-2.5-pro") is None


def test_a_provider_name_is_not_mistaken_for_the_keyless_engine_inside_it():
    # "Gemini API" contains "Gemini", which the substring search maps to the
    # old direct engine that reads no key from anywhere.
    assert TranslationFactory._get_engine_class("Gemini API") is GeminiProviderTranslation
    assert TranslationFactory._get_engine_class("Anthropic API") is AnthropicProviderTranslation


class TestModelLists:
    def test_openai_shape(self):
        body = {"data": [{"id": "gpt-5"}, {"id": "gpt-4.1"}, {"id": "gpt-5"}]}
        assert parse_model_list(provider("OpenAI API"), body) == ["gpt-4.1", "gpt-5"]

    def test_together_answers_with_a_bare_list(self):
        body = [{"id": "Qwen/Qwen2.5-72B"}, {"id": "deepseek-ai/DeepSeek-V3"}]
        assert parse_model_list(provider("Together API"), body) == ["Qwen/Qwen2.5-72B", "deepseek-ai/DeepSeek-V3"]

    def test_gemini_lists_only_models_that_generate_text(self):
        body = {"models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
        ]}
        assert parse_model_list(provider("Gemini API"), body) == ["gemini-2.5-flash"]


class TestSettings:
    """The real settings page: listed, saved, loaded, validated, cached by model."""

    @pytest.fixture
    def page(self, qapp):
        from app.ui.settings.settings_page import SettingsPage

        page = SettingsPage()
        yield page
        page.deleteLater()

    def test_every_provider_is_a_translator_and_has_a_section(self, page):
        translators = [page.ui.translator_combo.itemText(i) for i in range(page.ui.translator_combo.count())]
        for prov in PROVIDERS:
            assert prov.name in translators
            assert f"{prov.name}_api_key" in page.ui.credential_widgets
            assert f"{prov.name}_model" in page.ui.credential_widgets
        assert translators[-1] == "Custom"

    def test_key_and_model_survive_a_restart_with_save_keys(self, page, qapp):
        from app.ui.settings.settings_page import SettingsPage

        page.ui.save_keys_checkbox.setChecked(True)
        page.ui.credential_widgets["Mistral API_api_key"].setText("mk-1")
        page.ui.credential_widgets["Mistral API_model"].setText("mistral-small-latest")
        page.save_settings()

        again = SettingsPage()
        try:
            again.load_settings()
            creds = again.get_credentials("Mistral API")
            assert creds["api_key"] == "mk-1"
            assert creds["model"] == "mistral-small-latest"
        finally:
            again.deleteLater()

    def test_the_cache_key_changes_with_the_model(self, page):
        page.ui.translator_combo.setCurrentText("OpenAI API")
        assert page.get_translator_cache_key() == "OpenAI API|gpt-4.1-mini"
        page.ui.credential_widgets["OpenAI API_model"].setText("gpt-5")
        assert page.get_translator_cache_key() == "OpenAI API|gpt-5"
        page.ui.translator_combo.setCurrentText("OpenRouter")
        page.ui.credential_widgets["OpenRouter_model"].setText("google/gemini-2.5-flash")
        assert page.get_translator_cache_key() == "OpenRouter|google/gemini-2.5-flash"

    def test_a_provider_without_a_key_is_refused_with_its_name(self, page, monkeypatch):
        from app import validation

        shown = []
        monkeypatch.setattr(validation.Messages, "show_provider_key_missing_error",
                            lambda parent, name: shown.append(name))
        main = types.SimpleNamespace(settings_page=page)
        page.ui.translator_combo.setCurrentText("xAI API")
        page.ui.credential_widgets["xAI API_api_key"].setText("  ")
        assert validation.validate_translator(main, "Thai") is False
        assert shown == ["xAI API"]
        page.ui.credential_widgets["xAI API_api_key"].setText("xai-1")
        assert validation.validate_translator(main, "Thai") is True
