from __future__ import annotations

from collections.abc import Iterable
import os
import re
from typing import Any
from urllib.parse import unquote, urlsplit

REDACTION = "[REDACTED]"

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r"(?i)\b(authorization\s*:?\s*bearer|bearer)\s+([^\s,;]+)"
    ),
    re.compile(r"(?i)\b(api[_ -]?key|auth[_ -]?token|access[_ -]?token|secret)\s*[:=]\s*([^\s,;]+)"),
)


def sanitize_error_message(
    value: object,
    *,
    secrets: Iterable[str | None] = (),
    settings: Any | None = None,
    max_chars: int = 1000,
) -> str:
    message = str(value) or value.__class__.__name__
    for secret in _secret_values(secrets=secrets, settings=settings):
        message = _replace_secret(message, secret)
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(_redact_match, message)
    return message[:max_chars]


def _secret_values(
    *,
    secrets: Iterable[str | None],
    settings: Any | None,
) -> list[str]:
    values: list[str] = []
    for value in secrets:
        _append_secret(values, value, min_length=1)
    if settings is not None:
        _append_secret(values, getattr(settings, "deepseek_api_key", None), min_length=1)
        _append_secret(values, getattr(settings, "api_token", None), min_length=1)
        _append_url_secrets(values, getattr(settings, "redis_url", None))
        _append_url_secrets(values, getattr(settings, "database_url", None))
    _append_secret(values, os.environ.get("DEEPSEEK_API_KEY"), min_length=1)
    _append_secret(values, os.environ.get("QUANT_API_TOKEN"), min_length=1)
    return values


def _append_secret(
    values: list[str],
    value: str | None,
    *,
    min_length: int = 8,
) -> None:
    secret = (value or "").strip()
    if len(secret) >= min_length and secret not in values:
        values.append(secret)


def _append_url_secrets(values: list[str], value: str | None) -> None:
    url = (value or "").strip()
    if not url:
        return
    _append_secret(values, url, min_length=1)
    try:
        parsed = urlsplit(url)
    except ValueError:
        return
    for credential in (parsed.username, parsed.password):
        _append_secret(values, credential, min_length=1)
        _append_secret(values, unquote(credential or ""), min_length=1)


def _replace_secret(message: str, secret: str) -> str:
    if len(secret) >= 8:
        return message.replace(secret, REDACTION)
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(secret)}(?![A-Za-z0-9_])"
    )
    return pattern.sub(REDACTION, message)


def _redact_match(match: re.Match[str]) -> str:
    if len(match.groups()) >= 2:
        return f"{match.group(1)} {REDACTION}"
    return REDACTION
