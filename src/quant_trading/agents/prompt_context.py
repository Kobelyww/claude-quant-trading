from __future__ import annotations

import json
import re
from typing import Any

from quant_trading.security import sanitize_error_message

MEMORY_PROMPT_LIMIT = 8
SKILL_PROMPT_LIMIT = 20
MEMORY_CONTEXT_MAX_CHARS = 3000
SKILL_CONTEXT_MAX_CHARS = 1500
MEMORY_SUMMARY_MAX_CHARS = 500
SKILL_DESCRIPTION_MAX_CHARS = 500


def format_memory_context_for_prompt(
    memories: list[Any],
    *,
    redaction_settings: Any | None = None,
    max_chars: int | None = None,
) -> str:
    if not memories:
        return "- none"

    lines = []
    for memory in memories[:MEMORY_PROMPT_LIMIT]:
        payload = {
            "memory_type": _prompt_text(
                _field(memory, "memory_type", "unknown"),
                64,
                redaction_settings=redaction_settings,
            ),
            "reason_code": _prompt_text(
                _field(memory, "reason_code", "unspecified"),
                128,
                redaction_settings=redaction_settings,
            ),
            "summary": _memory_summary(
                memory,
                redaction_settings=redaction_settings,
            ),
        }
        line = (
            f"- [{payload['memory_type']}/{payload['reason_code']}] "
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )
        if max_chars is None:
            lines.append(line)
            continue
        current = "\n".join(lines)
        separator_len = 1 if current else 0
        remaining = max_chars - len(current) - separator_len
        if remaining <= 0:
            break
        if len(line) > remaining:
            lines.append(line[:remaining])
            break
        lines.append(line)
    if not lines:
        return ""
    if max_chars is None:
        return "\n".join(lines)
    return "\n".join(lines)[:max_chars]


def format_skill_context_for_prompt(
    skills: list[Any],
    *,
    redaction_settings: Any | None = None,
    max_chars: int | None = None,
) -> str:
    if not skills:
        return "- none; do not invent unsupported skills"

    lines = []
    for skill in skills[:SKILL_PROMPT_LIMIT]:
        skill_key = _prompt_text(
            _field(skill, "skill_key", "unknown"),
            64,
            redaction_settings=redaction_settings,
        )
        version = _prompt_text(
            _field(skill, "version", "unknown"),
            32,
            redaction_settings=redaction_settings,
        )
        display_name = _prompt_text(
            _field(skill, "display_name", ""),
            128,
            redaction_settings=redaction_settings,
        )
        guidance = _prompt_text(
            _field(skill, "prompt_guidance", ""),
            SKILL_DESCRIPTION_MAX_CHARS,
            redaction_settings=redaction_settings,
        )
        description = " ".join(
            part for part in (display_name, guidance) if part
        ).strip()
        if not description:
            description = "active strategy skill"
        bounded_description = description[:SKILL_DESCRIPTION_MAX_CHARS]
        line = f"- {skill_key} v{version}: {bounded_description}"
        if max_chars is None:
            lines.append(line)
            continue
        current = "\n".join(lines)
        separator_len = 1 if current else 0
        remaining = max_chars - len(current) - separator_len
        if remaining <= 0:
            break
        if len(line) > remaining:
            lines.append(line[:remaining])
            break
        lines.append(line)
    if not lines:
        return ""
    if max_chars is None:
        return "\n".join(lines)
    return "\n".join(lines)[:max_chars]


def sanitize_prompt_data(
    value: Any,
    *,
    redaction_settings: Any | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            _prompt_text(key, 160, redaction_settings=redaction_settings): sanitize_prompt_data(
                item,
                redaction_settings=redaction_settings,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            sanitize_prompt_data(item, redaction_settings=redaction_settings)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            sanitize_prompt_data(item, redaction_settings=redaction_settings)
            for item in value
        ]
    if isinstance(value, str):
        return _prompt_text(value, 4000, redaction_settings=redaction_settings)
    return value


def _memory_summary(
    memory: Any,
    *,
    redaction_settings: Any | None = None,
) -> str:
    title = _prompt_text(
        _field(memory, "title", ""),
        160,
        redaction_settings=redaction_settings,
    )
    content = _prompt_text(
        _field(memory, "content", ""),
        4000,
        redaction_settings=redaction_settings,
    )
    summary = " ".join(part for part in (title, content) if part).strip()
    if not summary:
        return "No summary provided."
    return summary[:MEMORY_SUMMARY_MAX_CHARS]


def _prompt_text(
    value: Any,
    limit: int,
    *,
    redaction_settings: Any | None = None,
) -> str:
    text = sanitize_error_message(
        str(value or ""),
        max_chars=limit,
        settings=redaction_settings,
    )
    text = re.sub(r"[\s\x00-\x1f\x7f]+", " ", text)
    text = text.replace(":", "：").strip()
    return _neutralize_prompt_directives(text)


def _neutralize_prompt_directives(text: str) -> str:
    patterns = (
        re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?\b"),
        re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior)\s+instructions?\b"),
        re.compile(r"(?i)\bignore\s+validation\s+floors?\b"),
        re.compile(r"(?i)\boverride\s+safety\s+constraints?\b"),
    )
    for pattern in patterns:
        text = pattern.sub("[NEUTRALIZED_DIRECTIVE]", text)
    return text


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
