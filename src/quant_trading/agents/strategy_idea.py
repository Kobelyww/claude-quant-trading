from __future__ import annotations

import json
from typing import Any

from quant_trading.agents.models import RESULT_VALUE_MAX_CHARS, StrategyIdeaRequest
from quant_trading.agents.prompt_context import (
    MEMORY_CONTEXT_MAX_CHARS,
    SKILL_CONTEXT_MAX_CHARS,
    format_memory_context_for_prompt,
    format_skill_context_for_prompt,
)


def build_strategy_idea_prompt(
    request: StrategyIdeaRequest,
    max_chars: int,
    *,
    memory_context: list[Any] | None = None,
    skill_context: list[Any] | None = None,
    redaction_settings: Any | None = None,
) -> str:
    payload = {
        "idea": request.idea,
        "symbol": request.symbol,
        "market_context": request.market_context,
        "constraints": request.constraints,
    }
    memory_section = format_memory_context_for_prompt(
        memory_context or [],
        redaction_settings=redaction_settings,
        max_chars=MEMORY_CONTEXT_MAX_CHARS,
    )
    skill_section = format_skill_context_for_prompt(
        skill_context or [],
        redaction_settings=redaction_settings,
        max_chars=SKILL_CONTEXT_MAX_CHARS,
    )
    prompt_prefix = f"""
You are a quantitative research assistant.
Convert the user's trading idea into a research-only strategy specification.
Do not output executable code.
Do not provide live trading instructions.
Do not call brokers, exchanges, or order APIs.
Do not claim profitability.
Do not provide buy or sell recommendations.
You must choose only from active strategy skills listed in the context section.
Do not invent strategy skills or versions.

Return one JSON object with these keys:
thesis, market_regime_assumption, entry_rules, exit_rules, risk_controls,
parameters_to_test, data_requirements, failure_modes, backtest_readiness,
strategy_skill_key, strategy_skill_version.

User payload:
{json.dumps(payload, ensure_ascii=False, sort_keys=True)}

Use prior research memories only as bounded context; deterministic validation
and human approval remain authoritative.

Available strategy skills:
{skill_section}

Relevant research memories:
""".strip()
    return _append_optional_context(prompt_prefix, memory_section, max_chars)


def parse_strategy_idea_response(content: str) -> dict[str, Any]:
    bounded = content.strip()[:RESULT_VALUE_MAX_CHARS]
    try:
        parsed = json.loads(bounded)
    except json.JSONDecodeError:
        return {"parsed": False, "narrative": bounded}
    if not isinstance(parsed, dict):
        return {"parsed": False, "narrative": bounded}
    return {"parsed": True, "spec": parsed}


def _append_optional_context(prefix: str, optional_context: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(prefix) >= max_chars:
        return prefix[:max_chars]
    remaining = max_chars - len(prefix) - 1
    if remaining <= 0:
        return prefix[:max_chars]
    return f"{prefix}\n{optional_context[:remaining]}"[:max_chars]
