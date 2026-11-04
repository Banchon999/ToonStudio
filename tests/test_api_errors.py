"""A provider's error reaches the user as what to do about it.

Engines used to raise the HTTP library's text ("402 Client Error: Payment
Required for url: …") and the app showed it in a traceback dialog.
"""

import json
import types

import pytest
import requests

from core.messages import api_error_text
from modules.utils import api_errors as ae
from modules.utils.api_errors import APIError, classify, provider_message


@pytest.mark.parametrize("status, message, kind", [
    (401, "No auth credentials found", ae.AUTH),
    (400, "Incorrect API key provided: sk-...", ae.AUTH),
    (403, "Key is not allowed to access this model", ae.AUTH),
    (402, "Insufficient credits. Add more using https://openrouter.ai/credits", ae.CREDIT),
    (429, "You exceeded your current quota, please check your plan", ae.CREDIT),
    (429, "Rate limit exceeded: free-models-per-min", ae.RATE_LIMIT),
    (404, "No endpoints found for google/gemini-9", ae.MODEL),
    (400, "openai/gpt-x is not a valid model ID", ae.MODEL),
    (400, "This model's maximum context length is 8192 tokens", ae.TOO_LONG),
    (413, "", ae.TOO_LONG),
    (403, "Input was flagged by moderation", ae.BLOCKED),
    (502, "Provider returned error", ae.SERVER),
    (408, "Timeout", ae.SERVER),
    (400, "Bad request", ae.OTHER),
])
def test_each_error_gets_the_answer_it_needs(status, message, kind):
    assert classify(status, message) == kind


def test_the_providers_own_words_are_found_in_each_body_shape():
    openai = json.dumps({"error": {"message": "Incorrect API key", "type": "invalid_request_error"}})
    routed = json.dumps({"error": {"message": "Provider returned error", "code": 502,
                                   "metadata": {"raw": "upstream overloaded"}}})
    assert provider_message(openai) == "Incorrect API key"
    assert provider_message(routed) == "Provider returned error (upstream overloaded)"
    assert provider_message(json.dumps({"error": "nope"})) == "nope"
    assert provider_message("<html>Bad gateway</html>") == "<html>Bad gateway</html>"


def test_the_text_says_what_to_do_and_keeps_the_providers_words():
    text = api_error_text(APIError("OpenRouter", 402, "Insufficient credits", "google/gemini-3.1-flash-lite"))
    assert "OpenRouter" in text and "credit" in text and "Insufficient credits" in text
    text = api_error_text(APIError("OpenRouter", 404, "No endpoints found", "google/gemini-9"))
    assert "google/gemini-9" in text


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return json.loads(self.text)


def _engine(monkeypatch, replies):
    from modules.translation.llm.openrouter import OpenRouterTranslation

    sent = []

    def post(url, headers=None, data=None, timeout=None):
        sent.append(json.loads(data))
        reply = replies[len(sent) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(requests, "post", post)
    engine = OpenRouterTranslation()
    engine.api_key, engine.model = "k", "openai/gpt-6-luna"
    engine.temperature, engine.top_p, engine.max_tokens = 0.3, 0.95, 100
    return engine, sent


def test_an_error_status_raises_an_api_error_naming_the_provider(monkeypatch):
    engine, _ = _engine(monkeypatch, [FakeResponse(402, {"error": {"message": "Insufficient credits"}})])
    with pytest.raises(APIError) as caught:
        engine._perform_translation("hi", "sys", None)
    assert (caught.value.provider, caught.value.kind, caught.value.model) == (
        "OpenRouter", ae.CREDIT, "openai/gpt-6-luna")


def test_a_model_that_refuses_temperature_is_asked_again_without_it(monkeypatch):
    refusal = FakeResponse(400, {"error": {"message": "Unsupported value: 'temperature' does not support 0.3"}})
    ok = FakeResponse(200, {"choices": [{"message": {"content": "สวัสดี"}}]})
    engine, sent = _engine(monkeypatch, [refusal, ok])
    assert engine._perform_translation("hi", "sys", None) == "สวัสดี"
    assert "temperature" in sent[0] and "temperature" not in sent[1] and "top_p" not in sent[1]


def test_a_network_failure_stays_a_network_error(monkeypatch):
    engine, _ = _engine(monkeypatch, [requests.exceptions.ConnectionError("down")])
    with pytest.raises(requests.exceptions.ConnectionError):
        engine._perform_translation("hi", "sys", None)


def test_the_window_shows_the_answer_not_a_traceback(monkeypatch):
    import controller
    from app.ui import messages

    shown = []
    monkeypatch.setattr(messages.Messages, "show_api_error", staticmethod(lambda parent, e: shown.append(e)))
    monkeypatch.setattr(messages.Messages, "show_error_with_copy",
                        staticmethod(lambda *a, **k: pytest.fail("traceback dialog shown")))
    fake = types.SimpleNamespace(loading=types.SimpleNamespace(setVisible=lambda v: None),
                                 enable_hbutton_group=lambda: None)
    error = APIError("OpenRouter", 429, "Rate limit exceeded")
    controller.ComicTranslate.default_error_handler(fake, (APIError, error, "tb"))
    assert shown == [error]


def test_translation_runs_at_a_low_temperature():
    from modules.translation.llm.base import TRANSLATION_TEMPERATURE
    from modules.translation.llm.claude import ClaudeTranslation
    from modules.translation.llm.openrouter import OpenRouterTranslation

    settings = types.SimpleNamespace(
        get_llm_settings=lambda: {"image_input_enabled": False},
        get_credentials=lambda name: {"api_key": "k", "model": "m"},
        ui=types.SimpleNamespace(tr=lambda s: s),
    )
    engine = OpenRouterTranslation()
    engine.initialize(settings, "Korean", "Thai")
    assert engine.temperature == TRANSLATION_TEMPERATURE <= 0.3
    claude = ClaudeTranslation()
    claude.initialize(settings, "Korean", "Thai", "Claude-4.5-Haiku")
    assert claude.temperature == TRANSLATION_TEMPERATURE / 2  # Anthropic's 0–1 scale
