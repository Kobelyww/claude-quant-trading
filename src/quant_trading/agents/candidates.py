from __future__ import annotations

from typing import Any

from quant_trading.agents.skills import (
    BACKTEST_MA_CROSS,
    REQUIRED_FIELDS,
    SAFETY_PATTERNS,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_PASSED,
    SUPPORTED_TEMPLATE,
    StrategySkillRegistry,
)


def validate_strategy_candidate(
    parsed_payload: dict[str, Any], *, request_symbol: str | None
) -> dict[str, Any]:
    return (
        StrategySkillRegistry.from_defaults()
        .validate_candidate(parsed_payload, request_symbol=request_symbol)
        .to_result_payload()
    )
