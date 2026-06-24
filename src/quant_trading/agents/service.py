from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Callable
from typing import Any
import json
import time

from sqlalchemy import Engine

from quant_trading.agents.candidates import validate_strategy_candidate
from quant_trading.agents.llm import DeepSeekLLMClient, LLMClient
from quant_trading.agents.market_analysis import build_market_analysis_prompt, compute_market_metrics
from quant_trading.agents.models import (
    AGENT_MARKET_ANALYSIS,
    AGENT_STRATEGY_IDEA,
    ERROR_MAX_CHARS,
    MARKET_CONTEXT_MAX_CHARS,
    RESEARCH_DISCLAIMER,
    REQUEST_VALUE_MAX_CHARS,
    MarketAnalysisRequest,
    StrategyIdeaRequest,
)
from quant_trading.agents.strategy_idea import (
    build_strategy_idea_prompt,
    parse_strategy_idea_response,
)
from quant_trading.config import AppSettings
from quant_trading.storage.db import session_scope
from quant_trading.storage.repositories import AgentRunRepository, MarketDataRepository


def run_market_analysis_agent(
    engine: Engine,
    request: MarketAnalysisRequest,
    *,
    llm_client: LLMClient | None = None,
    llm_client_factory: Callable[[AppSettings], LLMClient] | None = None,
    job_run_id: int | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    settings = settings or AppSettings()
    started_at = _utcnow()
    started_counter = time.perf_counter()
    request_payload = _json_dumps(
        {
            "symbol": request.symbol,
            "start": request.start.isoformat() if request.start else None,
            "end": request.end.isoformat() if request.end else None,
            "lookback_bars": request.lookback_bars,
            "mode": request.mode,
        }
    )

    with session_scope(engine) as session:
        row = AgentRunRepository(session).create_running(
            agent_type=AGENT_MARKET_ANALYSIS,
            symbol=request.symbol,
            model_name=getattr(llm_client, "model", settings.deepseek_model),
            request_payload=request_payload,
            job_run_id=job_run_id,
            started_at=started_at,
        )
        agent_run_id = row.id

    try:
        llm_client = llm_client or (llm_client_factory or DeepSeekLLMClient.from_settings)(settings)
        with session_scope(engine) as session:
            bars = MarketDataRepository(session).list_bars(request.symbol)
        if request.start:
            bars = [bar for bar in bars if bar.timestamp >= request.start]
        if request.end:
            bars = [bar for bar in bars if bar.timestamp <= request.end]
        metrics = compute_market_metrics(bars, request)
        prompt = build_market_analysis_prompt(metrics, request.mode, settings.agent_prompt_max_chars)
        response = llm_client.complete(prompt)
        result_payload = {
            "agent_run_id": agent_run_id,
            "agent_type": AGENT_MARKET_ANALYSIS,
            "symbol": request.symbol,
            "report": response.content[: settings.agent_result_max_chars],
            "research_only": True,
            "disclaimer": RESEARCH_DISCLAIMER,
        }
        finished_at = _utcnow()
        with session_scope(engine) as session:
            row = AgentRunRepository(session).get(agent_run_id)
            if row is not None:
                AgentRunRepository(session).mark_succeeded(
                    row,
                    metrics_payload=_json_dumps(metrics),
                    result_payload=_json_dumps(result_payload),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
        return result_payload
    except Exception as exc:
        finished_at = _utcnow()
        with session_scope(engine) as session:
            row = AgentRunRepository(session).get(agent_run_id)
            if row is not None:
                AgentRunRepository(session).mark_failed(
                    row,
                    _sanitize_error(exc),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
        raise


def run_strategy_idea_agent(
    engine: Engine,
    request: StrategyIdeaRequest,
    *,
    llm_client: LLMClient | None = None,
    llm_client_factory: Callable[[AppSettings], LLMClient] | None = None,
    job_run_id: int | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    settings = settings or AppSettings()
    started_at = _utcnow()
    started_counter = time.perf_counter()
    clean_request = StrategyIdeaRequest(
        idea=request.idea[:REQUEST_VALUE_MAX_CHARS],
        symbol=request.symbol.strip()[:32] if request.symbol else None,
        market_context=request.market_context[:MARKET_CONTEXT_MAX_CHARS]
        if request.market_context
        else None,
        constraints=request.constraints,
    )
    request_payload = _json_dumps(
        {
            "idea": clean_request.idea,
            "symbol": clean_request.symbol,
            "market_context": clean_request.market_context,
            "constraints": clean_request.constraints,
        }
    )
    with session_scope(engine) as session:
        row = AgentRunRepository(session).create_running(
            agent_type=AGENT_STRATEGY_IDEA,
            symbol=clean_request.symbol,
            model_name=getattr(llm_client, "model", settings.deepseek_model),
            request_payload=request_payload,
            job_run_id=job_run_id,
            started_at=started_at,
        )
        agent_run_id = row.id

    try:
        llm_client = llm_client or (llm_client_factory or DeepSeekLLMClient.from_settings)(settings)
        prompt = build_strategy_idea_prompt(clean_request, settings.agent_prompt_max_chars)
        response = llm_client.complete(prompt)
        parsed_payload = parse_strategy_idea_response(
            response.content[: settings.agent_result_max_chars]
        )
        if parsed_payload["parsed"]:
            validation_payload = validate_strategy_candidate(
                parsed_payload["spec"], request_symbol=clean_request.symbol
            )
        else:
            validation_payload = {
                "validation_status": "needs_review",
                "validation_errors": [],
                "safety_flags": [],
                "candidate_payload": None,
                "backtest_request_payload": None,
                "requires_human_approval": True,
            }
        result_payload = {
            "agent_run_id": agent_run_id,
            "agent_type": AGENT_STRATEGY_IDEA,
            "symbol": clean_request.symbol,
            "research_only": True,
            "disclaimer": RESEARCH_DISCLAIMER,
            **parsed_payload,
            **validation_payload,
        }
        finished_at = _utcnow()
        with session_scope(engine) as session:
            row = AgentRunRepository(session).get(agent_run_id)
            if row is not None:
                AgentRunRepository(session).mark_succeeded(
                    row,
                    metrics_payload="{}",
                    result_payload=_json_dumps(result_payload),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
        return result_payload
    except Exception as exc:
        finished_at = _utcnow()
        with session_scope(engine) as session:
            row = AgentRunRepository(session).get(agent_run_id)
            if row is not None:
                AgentRunRepository(session).mark_failed(
                    row,
                    _sanitize_error(exc),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
        raise


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _sanitize_error(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__)[:ERROR_MAX_CHARS]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _duration_ms(started_counter: float) -> int:
    return max(0, int((time.perf_counter() - started_counter) * 1000))
