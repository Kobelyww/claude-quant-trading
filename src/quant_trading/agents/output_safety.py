from __future__ import annotations

import re
from re import Pattern


UNSAFE_AGENT_TEXT_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"\b(?:buy|buying|sell|selling)\b", re.IGNORECASE),
    re.compile(r"\bpaper[-\s]+(?:trading|trade|run|runs)\b", re.IGNORECASE),
    re.compile(r"\b(?:broker|brokers|brokerage|exchange|exchanges)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:submit|place|send|create|execute)\b.{0,40}\b"
        r"(?:order|orders|market\s+order|market\s+orders)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:submit|place|send|create|execute)\b.{0,40}\b"
        r"(?:trade|trades|trading)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:trade|trades|trading)\b.{0,40}\b"
        r"(?:tomorrow|next\s+\w+|after\s+review|now|live|real\s+money)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:order|orders|market\s+order|market\s+orders)\b.{0,40}\b"
        r"(?:submit|place|send|create|execute)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bgo\s+live\b", re.IGNORECASE),
    re.compile(
        r"\blive\s+"
        r"(?:trade|trades|trading|order|orders|market\s+order|market\s+orders)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:real\s+money|real\s+capital|production\s+trading)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:open|close)\b.{0,30}\b(?:long|short)\s+position\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:long|short)\s+position\b", re.IGNORECASE),
    re.compile(r"\bmarket\s+orders?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:will|expect|expected|expects|expecting)\b.{0,40}\b"
        r"(?:profitable|positive\s+returns?|profit|profits|profitability|returns?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:guarantee|guarantees|guaranteed|guaranteeing)\b.{0,40}\b"
        r"(?:profit|profits|profitability|return|returns|gain|gains)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:future|guaranteed)\b.{0,40}\b"
        r"(?:profit|profits|profitability|return|returns|gain|gains)\b",
        re.IGNORECASE,
    ),
    re.compile(r"```", re.IGNORECASE),
    re.compile(r"\bdef\s+\w+\s*\(", re.IGNORECASE),
    re.compile(r"\bclass\s+\w+\s*[:(]", re.IGNORECASE),
    re.compile(r"\bimport\s+[\w.]+", re.IGNORECASE),
    re.compile(r"\bfrom\s+[\w.]+\s+import\s+\w+", re.IGNORECASE),
    re.compile(r"\bprint\s*\(", re.IGNORECASE),
    re.compile(r"^\s*[A-Za-z_]\w*\s*=\s*.+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*[A-Za-z_]\w*\s*\([^)]*\)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\b(?:executable|generated)\s+code\b", re.IGNORECASE),
    re.compile(r"\b(?:source\s+code|code\s+(?:block|snippet))\b", re.IGNORECASE),
)


def contains_unsafe_agent_text(values: list[str]) -> bool:
    for value in values:
        if any(pattern.search(value) for pattern in UNSAFE_AGENT_TEXT_PATTERNS):
            return True
    return False
