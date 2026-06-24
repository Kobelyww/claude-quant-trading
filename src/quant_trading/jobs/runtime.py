from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import json
import time
from typing import Any
from collections.abc import Callable

from sqlalchemy import Engine

from quant_trading.agents.llm import DeepSeekLLMClient, LLMClient
from quant_trading.agents.models import (
    BacktestReviewRequest,
    MarketAnalysisRequest,
    StrategyIdeaRequest,
)
from quant_trading.agents.service import (
    run_backtest_review_agent,
    run_market_analysis_agent,
    run_strategy_idea_agent,
)
from quant_trading.config import AppSettings
from quant_trading.data.providers.registry import build_default_provider_registry
from quant_trading.data.sync import sync_daily_market_data
from quant_trading.jobs.cancellation import CancellationToken, JobCancelled
from quant_trading.storage.db import make_engine, session_scope
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository
from quant_trading.workflows.operations import (
    import_legacy_data,
    run_ma_cross_backtest,
    run_paper_tick,
)
from quant_trading.workflows.runner import WorkflowCommandRunner, workflow_payload_dumps

IMPORT_LEGACY = "import_legacy"
BACKTEST_MA_CROSS = "backtest_ma_cross"
PAPER_RUN_TICK = "paper_run_tick"
MARKET_DATA_SYNC = "market_data_sync"
JOB_AGENT_MARKET_ANALYSIS = "agent_market_analysis"
JOB_AGENT_STRATEGY_IDEA = "agent_strategy_idea"
JOB_AGENT_BACKTEST_REVIEW = "agent_backtest_review"
SUPPORTED_JOB_TYPES = {
    IMPORT_LEGACY,
    BACKTEST_MA_CROSS,
    PAPER_RUN_TICK,
    MARKET_DATA_SYNC,
    JOB_AGENT_MARKET_ANALYSIS,
    JOB_AGENT_STRATEGY_IDEA,
    JOB_AGENT_BACKTEST_REVIEW,
}

AGENT_JOB_TYPES = {
    JOB_AGENT_MARKET_ANALYSIS,
    JOB_AGENT_STRATEGY_IDEA,
    JOB_AGENT_BACKTEST_REVIEW,
}


def execute_job_run(database_url: str, job_run_id: int) -> dict[str, Any]:
    engine = make_engine(database_url)
    return execute_job_run_with_engine(engine, job_run_id)


def execute_job_run_with_engine(engine: Engine, job_run_id: int) -> dict[str, Any]:
    started_at = utcnow()
    started_counter = time.perf_counter()
    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        job = repo.get(job_run_id)
        if job is None:
            raise ValueError(f"job run not found: {job_run_id}")
        if job.status == "cancelled":
            return {
                "job_run_id": job_run_id,
                "status": "cancelled",
                "error_message": "cancelled",
            }
        repo.mark_running(job, started_at=started_at)
        JobEventRepository(session).record(
            job.id,
            "running",
            "job started",
            progress=job.progress,
            created_at=started_at,
        )
        job_type = job.job_type
        request_payload = _json_loads(job.request_payload)
        if job_type in {MARKET_DATA_SYNC, *AGENT_JOB_TYPES}:
            request_payload = {**request_payload, "job_run_id": job_run_id}

    try:
        if job_type not in SUPPORTED_JOB_TYPES:
            raise ValueError(f"unsupported job type: {job_type}")
        cancellation_token = CancellationToken(engine, job_run_id)
        progress_callback = lambda progress, message: _record_progress(
            engine,
            job_run_id,
            progress,
            message,
        )
        execution = WorkflowCommandRunner(engine).run_with_audit(
            job_type,
            request_payload,
                lambda: _execute_payload(
                    engine,
                    job_type,
                    request_payload,
                    settings=_settings_from_agent_payload(request_payload)
                    if job_type in AGENT_JOB_TYPES
                    else None,
                    cancellation_token=cancellation_token,
                    progress_callback=progress_callback,
                ),
        )
    except JobCancelled as exc:
        finished_at = utcnow()
        duration_ms = _duration_ms(started_counter)
        with session_scope(engine) as session:
            repo = JobRunRepository(session)
            job = repo.get(job_run_id)
            if job is not None:
                repo.mark_cancelled(job, finished_at=finished_at, duration_ms=duration_ms)
                JobEventRepository(session).record(
                    job.id,
                    "cancelled",
                    "job cancelled",
                    progress=job.progress,
                    created_at=finished_at,
                )
        return {"job_run_id": job_run_id, "status": "cancelled", "error_message": str(exc)}
    except Exception as exc:
        finished_at = utcnow()
        duration_ms = _duration_ms(started_counter)
        error_message = _sanitize_error(exc)
        with session_scope(engine) as session:
            repo = JobRunRepository(session)
            job = repo.get(job_run_id)
            if job is not None:
                repo.mark_failed(job, error_message, finished_at, duration_ms)
                JobEventRepository(session).record(
                    job.id,
                    "failed",
                    error_message,
                    progress=job.progress,
                    created_at=finished_at,
                )
        return {"job_run_id": job_run_id, "status": "failed", "error_message": error_message}

    finished_at = utcnow()
    duration_ms = _duration_ms(started_counter)
    result_payload = (
        execution.result if isinstance(execution.result, dict) else {"result": execution.result}
    )
    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        job = repo.get(job_run_id)
        if job is not None:
            repo.mark_succeeded(
                job,
                result_payload=job_payload_dumps(result_payload),
                workflow_run_id=execution.workflow_run_id,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
            JobEventRepository(session).record(
                job.id,
                "succeeded",
                "job succeeded",
                progress=100,
                created_at=finished_at,
            )
    return {"job_run_id": job_run_id, "status": "succeeded", "result": result_payload}


def job_payload_dumps(payload: dict[str, Any]) -> str:
    return workflow_payload_dumps(payload)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def build_agent_llm_client(settings: AppSettings) -> LLMClient:
    return DeepSeekLLMClient.from_settings(settings)


def _execute_payload(
    engine: Engine,
    job_type: str,
    payload: dict[str, Any],
    *,
    settings: AppSettings | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    if job_type == IMPORT_LEGACY:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        return import_legacy_data(engine, str(payload["legacy_db_path"]))
    if job_type == BACKTEST_MA_CROSS:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        return run_ma_cross_backtest(
            engine,
            symbol=str(payload["symbol"]),
            short_window=int(payload["short_window"]),
            long_window=int(payload["long_window"]),
            order_size=int(payload["order_size"]),
            initial_cash=Decimal(str(payload["initial_cash"])),
        )
    if job_type == PAPER_RUN_TICK:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        return run_paper_tick(engine, int(payload["run_id"]))
    if job_type == MARKET_DATA_SYNC:
        return sync_daily_market_data(
            engine,
            provider_name=str(payload.get("provider", "akshare")),
            symbol=str(payload["symbol"]),
            start=payload.get("start"),
            end=payload.get("end"),
            registry=build_default_provider_registry(),
            job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
        )
    if job_type == JOB_AGENT_MARKET_ANALYSIS:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        settings = settings or _settings_from_agent_payload(payload)
        return run_market_analysis_agent(
            engine,
            MarketAnalysisRequest(
                symbol=str(payload["symbol"]),
                start=date.fromisoformat(payload["start"]) if payload.get("start") else None,
                end=date.fromisoformat(payload["end"]) if payload.get("end") else None,
                lookback_bars=int(payload.get("lookback_bars", 252)),
                mode=str(payload.get("mode", "overview")),
            ),
            llm_client_factory=build_agent_llm_client,
            job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
            settings=settings,
        )
    if job_type == JOB_AGENT_STRATEGY_IDEA:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        settings = settings or _settings_from_agent_payload(payload)
        return run_strategy_idea_agent(
            engine,
            StrategyIdeaRequest(
                idea=str(payload["idea"]),
                symbol=str(payload["symbol"]) if payload.get("symbol") else None,
                market_context=str(payload["market_context"])
                if payload.get("market_context")
                else None,
                constraints=payload.get("constraints")
                if isinstance(payload.get("constraints"), dict)
                else {},
            ),
            llm_client_factory=build_agent_llm_client,
            job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
            settings=settings,
        )
    if job_type == JOB_AGENT_BACKTEST_REVIEW:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        settings = settings or _settings_from_agent_payload(payload)
        return run_backtest_review_agent(
            engine,
            BacktestReviewRequest(
                candidate_review_id=int(payload["candidate_review_id"]),
                backtest_run_id=int(payload["backtest_run_id"])
                if payload.get("backtest_run_id")
                else None,
            ),
            llm_client_factory=build_agent_llm_client,
            job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
            settings=settings,
        )
    raise ValueError(f"unsupported job type: {job_type}")


def _record_progress(engine: Engine, job_run_id: int, progress: int, message: str) -> None:
    now = utcnow()
    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        job = repo.get(job_run_id)
        if job is not None:
            repo.update_progress(job, progress=progress, updated_at=now)
            JobEventRepository(session).record(
                job.id,
                "progress",
                message,
                progress=progress,
                created_at=now,
            )


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("job payload must be an object")
    return loaded


def _settings_from_agent_payload(payload: dict[str, Any]) -> AppSettings:
    return AppSettings(
        deepseek_api_base=str(payload.get("deepseek_api_base") or "https://api.deepseek.com"),
        deepseek_model=str(payload.get("deepseek_model") or "deepseek-v4-pro"),
        agent_prompt_max_chars=int(payload.get("agent_prompt_max_chars") or 8000),
        agent_result_max_chars=int(payload.get("agent_result_max_chars") or 12000),
    )


def _duration_ms(started_counter: float) -> int:
    return max(0, int((time.perf_counter() - started_counter) * 1000))


def _sanitize_error(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__)[:1000]
