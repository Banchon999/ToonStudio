from typing import Any

import numpy as np

from modules.utils.openrouter_models import NAMED_MODELS, TEXT_ONLY_MODELS, missing_key_message
from .gpt import GPTTranslation


class OpenRouterTranslation(GPTTranslation):
    """Translation engine using OpenRouter's OpenAI-compatible API.

    OpenRouter (https://openrouter.ai) routes a single API key to many
    hosted models; the user picks the model id (e.g. "openai/gpt-4o",
    "anthropic/claude-sonnet-4.5") in the credentials settings.
    """

    # OpenRouter expects the standard OpenAI "max_tokens" parameter
    MAX_TOKENS_PARAM = "max_tokens"

    def __init__(self):
        super().__init__()
        self.api_base_url = "https://openrouter.ai/api/v1"

    def initialize(self, settings: Any, source_lang: str, target_lang: str, tr_key: str = "OpenRouter", **kwargs) -> None:
        """
        Initialize OpenRouter translation engine.

        Args:
            settings: Settings object with credentials
            source_lang: Source language name
            target_lang: Target language name
            tr_key: Key identifying the translator ("OpenRouter")
        """
        # Call BaseLLMTranslation's initialize, not GPTTranslation's,
        # to avoid the GPT-specific credential loading
        super(GPTTranslation, self).initialize(settings, source_lang, target_lang, **kwargs)

        credentials = settings.get_credentials(settings.ui.tr("OpenRouter"))
        # A pasted key often carries a space or newline; sent as is, the
        # header is rejected the same way as no key at all.
        self.api_key = (credentials.get('api_key') or '').strip()
        # A named model (GPT-4.1, Gemini-3.1-Flash-Lite...) brings its own
        # id; "OpenRouter" itself uses the model typed in the settings.
        self.model = NAMED_MODELS.get(tr_key) or (credentials.get('model') or '').strip()
        if tr_key in TEXT_ONLY_MODELS:
            self.supports_images = False
        self.timeout = 120  # Routed models can be slower than first-party APIs

    def _perform_translation(self, user_prompt: str, system_prompt: str, image: np.ndarray) -> str:
        # Without a key OpenRouter answers "401 Missing Authentication
        # header", which says nothing about where the key goes.
        if not self.api_key:
            raise RuntimeError(missing_key_message())
        return super()._perform_translation(user_prompt, system_prompt, image)
