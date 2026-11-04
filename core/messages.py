"""User-facing message text built off the UI thread.

`app/ui/messages.py`'s `Messages` is a widget layer — every `show_*` builds a
dialog. Two of its members are not: they only assemble localised strings, and
the pipeline calls them from worker threads precisely because they touch
nothing. Those live here, where a headless process can reach them.

`Messages` keeps its methods as thin delegates so existing call sites and the
UI keep working unchanged.
"""

from __future__ import annotations

from core.i18n import translate


def server_error_text(status_code: int = 500, context: str | None = None) -> str:
    """Localised text for a 5xx from the hosted backend.

    Touches no UI. Call it from a worker thread, then hand the result to the
    GUI thread through a signal.

    Args:
        status_code: HTTP status code (500, 501, 502, 503, 504).
        context: 'ocr', 'translation', or None for the generic wording.
    """
    if status_code == 501:
        if context == 'ocr':
            return translate("Messages", "The selected text recognition tool is not supported.\nPlease select a different tool in Settings.")
        elif context == 'translation':
            return translate("Messages", "The selected translator is not supported.\nPlease select a different tool in Settings.")
        else:
            return translate("Messages", "The selected tool is not supported.\nPlease select a different tool in Settings.")

    messages = {
        500: translate("Messages", "We encountered an unexpected server error.\nPlease try again in a few moments."),
        502: translate("Messages", "The external service provider is having trouble.\nPlease try again later."),
        503: translate("Messages", "The server is currently busy or under maintenance.\nPlease try again shortly."),
        504: translate("Messages", "The server took too long to respond.\nPlease check your connection or try again later."),
    }
    return messages.get(status_code, messages[500])


def api_error_text(error) -> str:
    """Localised text for a `modules.utils.api_errors.APIError`.

    What the user can do about it first, then the provider's own words, which
    are often the only place the real reason is (a model id typo, a region).
    """
    # The kinds are modules.utils.api_errors' constants, spelt out so core
    # does not import modules.
    AUTH, CREDIT, RATE_LIMIT, MODEL, TOO_LONG, BLOCKED, SERVER = (
        "auth", "credit", "rate_limit", "model", "too_long", "blocked", "server",
    )
    provider = getattr(error, "provider", "") or "The AI provider"
    model = getattr(error, "model", "") or "?"
    status = getattr(error, "status", 0)
    kind = getattr(error, "kind", "")
    if kind == AUTH:
        text = translate(
            "Messages",
            "{0} rejected the API key.\nCheck the key in Settings (and tick Save Keys to keep it).",
        ).format(provider)
    elif kind == CREDIT:
        text = translate(
            "Messages",
            "{0}: the account has run out of credit.\nTop it up, or choose a cheaper model.",
        ).format(provider)
    elif kind == RATE_LIMIT:
        text = translate(
            "Messages",
            "{0} is limiting requests (too many in a short time).\nWait a minute and try again, or choose another model.",
        ).format(provider)
    elif kind == MODEL:
        text = translate(
            "Messages",
            "{0} cannot find the model \"{1}\".\nCheck the model name in Settings.",
        ).format(provider, model)
    elif kind == TOO_LONG:
        text = translate(
            "Messages",
            "The page is more than the model \"{0}\" accepts in one request.\n"
            "Choose a model with a larger context, or translate fewer pages at once.",
        ).format(model)
    elif kind == BLOCKED:
        text = translate(
            "Messages",
            "{0} refused this content.\nTry a different model.",
        ).format(provider)
    elif kind == SERVER:
        text = translate(
            "Messages",
            "{0} is having problems (HTTP {1}).\nTry again later, or choose another model.",
        ).format(provider, status)
    else:
        text = translate(
            "Messages",
            "{0} refused the request (HTTP {1}).",
        ).format(provider, status)
    detail = (getattr(error, "detail", "") or "").strip()
    if detail:
        text += "\n\n" + translate("Messages", "The service said: {0}").format(detail[:300])
    return text


def content_flagged_text(details: str | None = None, context: str = "Operation") -> str:
    """Localised text for a provider refusing content as flagged.

    `details` is accepted and ignored, as it always has been — the provider's
    own explanation is not shown to the user. Kept in the signature so call
    sites do not have to change.
    """
    if context == "OCR":
        return translate(
            "Messages",
            "Text Recognition blocked: The AI provider flagged this content.\nPlease try a different Text Recognition tool."
        )
    elif context in ("Translator", "Translation"):
        return translate(
            "Messages",
            "Translation blocked: The AI provider flagged this content.\nPlease try a different translator."
        )
    return translate(
        "Messages",
        "Operation blocked: The AI provider flagged this content.\nPlease try a different tool."
    )
