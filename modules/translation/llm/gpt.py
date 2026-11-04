from typing import Any
import numpy as np
import requests
import json

from .base import BaseLLMTranslation
from ...utils.api_errors import APIError, rejects_sampling
from ...utils.translator_utils import MODEL_MAP


class GPTTranslation(BaseLLMTranslation):
    """Translation engine using OpenAI GPT models through direct REST API calls."""

    # Name of the max-token request parameter; subclasses targeting other
    # OpenAI-compatible APIs may override (e.g. OpenRouter uses "max_tokens").
    MAX_TOKENS_PARAM = "max_completion_tokens"

    # Named in the error a user sees when the API refuses a request.
    PROVIDER = "OpenAI"

    def __init__(self):
        super().__init__()
        self.model_name = None
        self.api_key = None
        self.api_base_url = "https://api.openai.com/v1"
        self.supports_images = True
    
    def initialize(self, settings: Any, source_lang: str, target_lang: str, model_name: str, **kwargs) -> None:
        """
        Initialize GPT translation engine.
        
        Args:
            settings: Settings object with credentials
            source_lang: Source language name
            target_lang: Target language name
            model_name: GPT model name
        """
        super().initialize(settings, source_lang, target_lang, **kwargs)
        
        self.model_name = model_name
        credentials = settings.get_credentials(settings.ui.tr('Open AI GPT'))
        self.api_key = credentials.get('api_key', '')
        self.model = MODEL_MAP.get(self.model_name)
    
    def _perform_translation(self, user_prompt: str, system_prompt: str, image: np.ndarray) -> str:
        """
        Perform translation using direct REST API calls to OpenAI.
        
        Args:
            user_prompt: Text prompt from user
            system_prompt: System instructions
            image: Image as numpy array
            
        Returns:
            Translated text
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        if self.supports_images and self.img_as_llm_input:
            # Use the base class method to encode the image
            encoded_image, mime_type = self.encode_image(image)
            
            messages = [
                {
                    "role": "system", 
                    "content": [{"type": "text", "text": system_prompt}]
                },
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}}
                    ]
                }
            ]
        else:
            messages = [
                {
                    "role": "system", 
                    "content": [{"type": "text", "text": system_prompt}]
                },
                {
                    "role": "user", 
                    "content": [{"type": "text", "text": user_prompt}]
                }
            ]

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            self.MAX_TOKENS_PARAM: self.max_tokens,
            "top_p": self.top_p,
        }

        return self._make_api_request(payload, headers)
    
    def _make_api_request(self, payload, headers):
        """POST the request; an error status raises APIError.

        Reasoning models accept only their default temperature and top_p and
        answer 400 to anything else; that request is sent once more without
        them rather than failing the page.
        """
        response = self._post(payload, headers)
        if response.status_code == 400 and ("temperature" in payload or "top_p" in payload):
            error = APIError.from_response(self.PROVIDER, response, self.model or "")
            if rejects_sampling(error.status, error.detail):
                payload = {k: v for k, v in payload.items() if k not in ("temperature", "top_p")}
                response = self._post(payload, headers)
        if not 200 <= response.status_code < 300:
            raise APIError.from_response(self.PROVIDER, response, self.model or "")
        return response.json()["choices"][0]["message"]["content"]

    def _post(self, payload, headers):
        # Network failures stay requests exceptions: the UI already says
        # "check your connection" for those.
        return requests.post(
            f"{self.api_base_url}/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=self.timeout,
        )