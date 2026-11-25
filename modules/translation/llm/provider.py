"""Translation on a provider's own API key (see modules/utils/llm_providers).

Three protocols cover every provider in the table: OpenAI's chat
completions (OpenAI, DeepSeek, xAI, Mistral, Groq, Together), Anthropic's
messages and Gemini's generateContent. Each class only loads the key and
model from the provider's settings section; the requests themselves are the
existing engines'.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from modules.utils.api_errors import APIError
from modules.utils.llm_providers import Provider, chosen_model, missing_key_message, provider
from .base import BaseLLMTranslation
from .claude import ClaudeTranslation
from .gemini import GeminiTranslation
from .gpt import GPTTranslation

logger = logging.getLogger(__name__)


def _load(engine, settings: Any, name: str) -> Provider:
    prov = provider(name)
    if prov is None:
        raise ValueError(f"Unknown provider: {name}")
    creds = settings.get_credentials(name) or {}
    # A pasted key often carries a space or newline; sent as is, it is
    # refused the same way as no key at all.
    engine.api_key = (creds.get("api_key") or "").strip()
    engine.model = chosen_model(prov, creds)
    engine.provider = prov
    engine.PROVIDER = prov.company
    engine.timeout = 120
    return prov


def _require_key(engine) -> None:
    if not engine.api_key:
        raise RuntimeError(missing_key_message(engine.provider))


def _refuses_image(error: APIError) -> bool:
    """Whether a refused request may be the model refusing the image.

    Most providers answer a text-only model's image with a 400 or 422 (in
    their own words: "image input", "unknown variant `image_url`"...); a
    router answers 404 "No endpoints found that support image input" — seen
    from OpenRouter, which the Groq and Together rows also front models for.
    A 404 counts only when it names the image: it is also an unknown model.
    """
    if error.status in (400, 415, 422):
        return True
    return error.status == 404 and "image" in (error.detail or "").lower()


class ProviderTranslation(GPTTranslation):
    """Any provider speaking OpenAI's chat completions protocol."""

    def initialize(self, settings: Any, source_lang: str, target_lang: str, tr_key: str, **kwargs) -> None:
        BaseLLMTranslation.initialize(self, settings, source_lang, target_lang, **kwargs)
        prov = _load(self, settings, tr_key)
        self.api_base_url = prov.base_url
        self.MAX_TOKENS_PARAM = prov.max_tokens_param
        self.supports_images = prov.images

    def _perform_translation(self, user_prompt: str, system_prompt: str, image: np.ndarray) -> str:
        _require_key(self)
        if self.supports_images and self.img_as_llm_input and image is not None:
            encoded, mime = self.encode_image(image)
            user_content = [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ]
        else:
            user_content = user_prompt
        # Plain strings rather than OpenAI's list of parts wherever there is
        # no image: not every provider accepts parts in a system message.
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.temperature,
            self.MAX_TOKENS_PARAM: self.max_tokens,
            "top_p": self.top_p,
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        try:
            return self._make_api_request(payload, headers)
        except APIError as error:
            if isinstance(user_content, str) or not _refuses_image(error):
                raise
            # Many models these providers serve read text only, and say so
            # with a 400. The page image is an aid, not the job: drop it and
            # stop sending it for the rest of the session.
            logger.warning("%s refused the page image (%s); sending text only from now on",
                           self.model, error.detail)
            self.supports_images = False
            payload["messages"][1]["content"] = user_prompt
            return self._make_api_request(payload, headers)


class AnthropicProviderTranslation(ClaudeTranslation):
    def initialize(self, settings: Any, source_lang: str, target_lang: str, tr_key: str, **kwargs) -> None:
        BaseLLMTranslation.initialize(self, settings, source_lang, target_lang, **kwargs)
        # Anthropic's temperature runs 0–1, half OpenAI's scale.
        self.temperature = self.temperature / 2
        prov = _load(self, settings, tr_key)
        self.api_url = f"{prov.base_url}/messages"
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _perform_translation(self, user_prompt: str, system_prompt: str, image: np.ndarray) -> str:
        _require_key(self)
        return super()._perform_translation(user_prompt, system_prompt, image)


class GeminiProviderTranslation(GeminiTranslation):
    def initialize(self, settings: Any, source_lang: str, target_lang: str, tr_key: str, **kwargs) -> None:
        BaseLLMTranslation.initialize(self, settings, source_lang, target_lang, **kwargs)
        prov = _load(self, settings, tr_key)
        self.api_base_url = f"{prov.base_url}/models"
        self.model_name = self.model
        self.model_api_name = self.model

    def _perform_translation(self, user_prompt: str, system_prompt: str, image: np.ndarray) -> str:
        _require_key(self)
        return super()._perform_translation(user_prompt, system_prompt, image)


ENGINES = {
    "openai": ProviderTranslation,
    "anthropic": AnthropicProviderTranslation,
    "gemini": GeminiProviderTranslation,
}


def engine_class_for(name: str):
    """The engine class for a provider's translator name, or None."""
    prov = provider(name)
    return ENGINES[prov.protocol] if prov else None
