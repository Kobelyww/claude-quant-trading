from __future__ import annotations

import json
from typing import Any

from quant_trading.agents.models import RESULT_VALUE_MAX_CHARS, StrategyIdeaRequest


def build_strategy_idea_prompt(request: StrategyIdeaRequest, max_chars: int) -> str:
    payload = {
        "idea": request.idea,
        "symbol": request.symbol,
        "market_context": request.market_context,
        "constraints": request.constraints,
    }
    prompt = f"""
You are a quantitative research assistant.
Convert the user's trading idea into a research-only strategy specification.
Do not output executable code.
Do not provide live trading instructions.
Do not call brokers, exchanges, or order APIs.
Do not claim profitability.
Do not provide buy or sell recommendations.

Return one JSON object with these keys:
thesis, market_regime_assumption, entry_rules, exit_rules, risk_controls,
parameters_to_test, data_requirements, failure_modes, backtest_readiness.

User payload:
{json.dumps(payload, ensure_ascii=False, sort_keys=True)}
""".strip()
    return prompt[:max_chars]


def parse_strategy_idea_response(content: str) -> dict[str, Any]:
    bounded = content.strip()[:RESULT_VALUE_MAX_CHARS]
    try:
        parsed = json.loads(bounded)
    except json.JSONDecodeError:
        return {"parsed": False, "narrative": bounded}
    if not isinstance(parsed, dict):
        return {"parsed": False, "narrative": bounded}
    return {"parsed": True, "spec": parsed}
