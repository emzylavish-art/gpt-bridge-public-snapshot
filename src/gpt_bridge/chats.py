from __future__ import annotations

from urllib.parse import urlparse


class ChatTargetError(ValueError):
    pass


def normalize_chat_target(value: str | None) -> str | None:
    """Accept 'new' or one of your own ChatGPT conversation URLs. Nothing else."""

    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.lower() == "new":
        return "new"
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in {"chatgpt.com", "www.chatgpt.com"}:
        raise ChatTargetError("chat url must be https://chatgpt.com/c/... or https://chatgpt.com/uc/...")
    if not (parsed.path.startswith("/c/") or parsed.path.startswith("/uc/")):
        raise ChatTargetError("chat url must be a conversation link, not the home page")
    if parsed.username or parsed.password:
        raise ChatTargetError("chat url must not contain credentials")
    return f"https://chatgpt.com{parsed.path}"
