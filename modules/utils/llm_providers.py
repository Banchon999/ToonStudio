"""The AI providers a translation can be sent to directly, on their own key.

The named models in the translator list (GPT-4.1, Claude-4.6-Sonnet, ...)
run on the OpenRouter key; these run on the provider's own key, with any
model that provider serves. Each is one entry in the translator list and one
section in Settings > Advanced (an API key and a model), and both read this
table, so adding a provider is adding a row here.

Qt-free: the engines, the factory, validation and the settings page all
read it.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

#: How a provider is spoken to.
OPENAI_COMPATIBLE = "openai"
ANTHROPIC = "anthropic"
GEMINI = "gemini"


@dataclass(frozen=True)
class Provider:
    #: Translator name, credential service and settings key, all at once.
    #: Never rename one: saved settings and keys are stored under it.
    name: str
    #: Named in the error a user sees when the API refuses a request.
    company: str
    protocol: str
    base_url: str
    #: Used when the Model field is left empty; the first of `models`.
    models: tuple[str, ...]
    #: Where to make a key, shown beside the key field.
    key_url: str
    #: OpenAI renamed max_tokens to max_completion_tokens; most others did not.
    max_tokens_param: str = "max_tokens"
    #: Whether the page image may be sent. A model that turns out to refuse
    #: images is retried once without one and not sent one again.
    images: bool = True

    @property
    def default_model(self) -> str:
        return self.models[0]


#: In the order they are listed. Model ids are suggestions — the field takes
#: any id the provider serves, and "Refresh" asks the provider for its list.
PROVIDERS: tuple[Provider, ...] = (
    Provider(
        name="OpenAI API", company="OpenAI", protocol=OPENAI_COMPATIBLE,
        base_url="https://api.openai.com/v1",
        models=("gpt-4.1-mini", "gpt-4.1", "gpt-5-mini", "gpt-5"),
        key_url="https://platform.openai.com/api-keys",
        max_tokens_param="max_completion_tokens",
    ),
    Provider(
        name="Anthropic API", company="Anthropic", protocol=ANTHROPIC,
        base_url="https://api.anthropic.com/v1",
        models=("claude-haiku-4-5", "claude-sonnet-4-6"),
        key_url="https://console.anthropic.com/settings/keys",
    ),
    Provider(
        name="Gemini API", company="Google", protocol=GEMINI,
        base_url="https://generativelanguage.googleapis.com/v1beta",
        models=("gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"),
        key_url="https://aistudio.google.com/apikey",
    ),
    Provider(
        name="DeepSeek API", company="DeepSeek", protocol=OPENAI_COMPATIBLE,
        base_url="https://api.deepseek.com/v1",
        models=("deepseek-chat", "deepseek-reasoner"),
        key_url="https://platform.deepseek.com/api_keys",
        images=False,
    ),
    Provider(
        name="xAI API", company="xAI", protocol=OPENAI_COMPATIBLE,
        base_url="https://api.x.ai/v1",
        models=("grok-4", "grok-3-mini"),
        key_url="https://console.x.ai",
    ),
    Provider(
        name="Mistral API", company="Mistral", protocol=OPENAI_COMPATIBLE,
        base_url="https://api.mistral.ai/v1",
        models=("mistral-medium-latest", "mistral-large-latest", "mistral-small-latest"),
        key_url="https://console.mistral.ai/api-keys",
    ),
    Provider(
        name="Groq API", company="Groq", protocol=OPENAI_COMPATIBLE,
        base_url="https://api.groq.com/openai/v1",
        models=("openai/gpt-oss-120b", "llama-3.3-70b-versatile", "moonshotai/kimi-k2-instruct"),
        key_url="https://console.groq.com/keys",
    ),
    Provider(
        name="Together API", company="Together AI", protocol=OPENAI_COMPATIBLE,
        base_url="https://api.together.xyz/v1",
        models=("deepseek-ai/DeepSeek-V3", "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "Qwen/Qwen2.5-72B-Instruct-Turbo"),
        key_url="https://api.together.xyz/settings/api-keys",
    ),
)

_BY_NAME = {p.name: p for p in PROVIDERS}
PROVIDER_NAMES: tuple[str, ...] = tuple(_BY_NAME)


def provider(name: str) -> Provider | None:
    """The provider a translator or credential name stands for, if any."""
    return _BY_NAME.get(name)


def chosen_model(prov: Provider, credentials: dict | None) -> str:
    """The model to send: the one typed in the settings, else the default."""
    typed = ((credentials or {}).get("model") or "").strip()
    return typed or prov.default_model


def credential_fields(service: str) -> tuple[str, ...]:
    """The fields a credentials section stores, by its internal name."""
    if service == "Custom":
        return ("api_key", "api_url", "model")
    if service == "OpenRouter":
        return ("api_key", "model", "ocr_model")
    if service in _BY_NAME:
        return ("api_key", "model")
    return ()


def missing_key_message(prov: Provider) -> str:
    return (
        f"No API key is set for {prov.name}. Enter it under Settings > Advanced > "
        f"{prov.name}, and tick Save Keys to keep it after restarting."
    )


def list_models(prov: Provider, api_key: str, timeout: float = 15) -> list[str]:
    """The model ids the provider serves to this key, sorted.

    Raises on a network failure or a refused key; the caller says so.
    """
    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("Enter the API key first.")
    if prov.protocol == ANTHROPIC:
        response = requests.get(
            f"{prov.base_url}/models?limit=1000",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=timeout,
        )
    elif prov.protocol == GEMINI:
        response = requests.get(
            f"{prov.base_url}/models?pageSize=1000",
            headers={"x-goog-api-key": api_key},
            timeout=timeout,
        )
    else:
        response = requests.get(
            f"{prov.base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    response.raise_for_status()
    return parse_model_list(prov, response.json())


def parse_model_list(prov: Provider, body) -> list[str]:
    """Model ids out of a /models answer, in each provider's shape."""
    if prov.protocol == GEMINI:
        ids = []
        for m in (body or {}).get("models", []):
            methods = m.get("supportedGenerationMethods") or []
            name = (m.get("name") or "").removeprefix("models/")
            if name and (not methods or "generateContent" in methods):
                ids.append(name)
        return sorted(set(ids))
    # OpenAI, Anthropic and most others: {"data": [{"id": ...}]}; Together
    # answers with the bare list.
    rows = body.get("data", []) if isinstance(body, dict) else body
    ids = [r.get("id") for r in rows or [] if isinstance(r, dict) and r.get("id")]
    return sorted(set(ids))

