from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

AGENT_MARKET_ANALYSIS = "market_analysis"
AGENT_STRATEGY_IDEA = "strategy_idea"

STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

REQUEST_VALUE_MAX_CHARS = 4000
MARKET_CONTEXT_MAX_CHARS = 2000
DEFAULT_LOOKBACK_BARS = 252
MIN_LOOKBACK_BARS = 60
MAX_LOOKBACK_BARS = 1000
PROMPT_MAX_CHARS = 8000
RESULT_VALUE_MAX_CHARS = 12000
ERROR_MAX_CHARS = 1000

RESEARCH_DISCLAIMER = (
    "This output is for quantitative research only. It is not investment advice, "
    "does not predict future prices, and must not be used as an instruction to trade."
)


@dataclass(frozen=True)
class MarketAnalysisRequest:
    symbol: str
    start: date | None = None
    end: date | None = None
    lookback_bars: int = DEFAULT_LOOKBACK_BARS
    mode: str = "overview"


@dataclass(frozen=True)
class StrategyIdeaRequest:
    idea: str
    symbol: str | None = None
    market_context: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    agent_type: str
    model_name: str
    request_payload: dict[str, Any]
    metrics_payload: dict[str, Any]
    result_payload: dict[str, Any]
