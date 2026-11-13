"""Errors from an AI provider's API, sorted into what the user can do about them.

An engine used to raise whatever text the HTTP call produced — "API request
failed: 402 Client Error: Payment Required for url: … - {"error": …}" — and
the app showed it in a traceback dialog. The user needs one of a handful of
answers instead: the key is wrong, the credit has run out, slow down, the
model name is wrong, the page is too long, the provider is down. `APIError`
carries the status and the provider's own message; `kind` says which answer
applies, and `core.messages.api_error_text` turns it into words.

Qt-free, so engines and the pipeline can raise and classify it anywhere.
"""

from __future__ import annotations

import json

AUTH = "auth"              # the key is missing, wrong, revoked or not allowed
CREDIT = "credit"          # no credit or quota left on the account
RATE_LIMIT = "rate_limit"  # too many requests in a short time
MODEL = "model"            # the model id does not exist or has no provider
TOO_LONG = "too_long"      # the request is more than the model accepts
BLOCKED = "blocked"        # the provider refused the content
SERVER = "server"          # the provider (or the model's host) is failing
BAD_REPLY = "bad_reply"    # the model answered, but not in a form the app can read
OTHER = "other"


def provider_message(body: str) -> str:
    """The provider's own explanation, out of whatever shape its error body has."""
    text = (body or "").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return text[:300]
    error = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(error, dict):
        message = error.get("message") or error.get("detail") or error.get("type") or ""
        raw = (error.get("metadata") or {}).get("raw") if isinstance(error.get("metadata"), dict) else None
        if raw and isinstance(raw, str) and raw not in message:
            # OpenRouter puts the routed provider's own words here.
            message = f"{message} ({raw})" if message else raw
        return str(message)[:300]
    if isinstance(error, str):
        return error[:300]
    return text[:300]


def classify(status: int, message: str = "") -> str:
    """Which of the answers above a status and provider message call for."""
    m = (message or "").lower()
    if status == 402 or "insufficient credit" in m or "insufficient_quota" in m or "exceeded your current quota" in m:
        return CREDIT
    if status == 401 or "invalid api key" in m or "invalid_api_key" in m or "incorrect api key" in m:
        return AUTH
    if status == 429:
        return RATE_LIMIT
    if status == 413 or any(s in m for s in (
        "context length", "maximum context", "context window", "too many tokens", "token limit",
        "prompt is too long", "request too large",
    )):
        return TOO_LONG
    if status == 404 or "no endpoints found" in m or (
        "model" in m and any(s in m for s in ("not found", "does not exist", "not a valid model", "invalid model"))
    ):
        return MODEL
    if status == 403 and any(s in m for s in ("moderation", "flagged", "safety", "content policy", "blocked")):
        return BLOCKED
    if status == 403:
        return AUTH
    if status == 408 or status >= 500:
        return SERVER
    return OTHER


def rejects_sampling(status: int, message: str = "") -> bool:
    """A 400 refusing temperature/top_p — reasoning models accept only their default."""
    m = (message or "").lower()
    return status == 400 and ("temperature" in m or "top_p" in m)


class APIError(RuntimeError):
    """A provider answered with an error status."""

    def __init__(self, provider: str, status: int, message: str = "", model: str = ""):
        self.provider = provider or "The AI provider"
        self.status = int(status)
        self.detail = message or ""
        self.model = model or ""
        self.kind = classify(self.status, self.detail)
        super().__init__(
            f"{self.provider} answered HTTP {self.status}"
            + (f" for model {self.model}" if self.model else "")
            + (f": {self.detail}" if self.detail else "")
        )

    @classmethod
    def bad_reply(cls, provider: str, model: str, detail: str) -> "APIError":
        """The model answered twice with a translation the app could not read
        (`translator_utils.parse_reply_json` gave up on both)."""
        error = cls(provider, 0, detail, model)
        error.kind = BAD_REPLY
        return error

    @classmethod
    def from_response(cls, provider: str, response, model: str = "") -> "APIError":
        return cls(provider, response.status_code, provider_message(response.text), model)
