from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from quant_trading.api.job_streaming import ensure_job_exists, iter_job_event_sse
from quant_trading.api.routes.workflows import ImportLegacyRequest, MACrossBacktestRequest
from quant_trading.jobs.queue import make_queue
from quant_trading.jobs.runtime import (
    BACKTEST_MA_CROSS,
    DATA_QUALITY_REPORT,
    IMPORT_LEGACY,
    JOB_AGENT_BACKTEST_REVIEW,
    JOB_AGENT_MARKET_ANALYSIS,
    JOB_AGENT_STRATEGY_IDEA,
    MARKET_DATA_SYNC,
    PAPER_RUN_TICK,
    RESEARCH_VALIDATION,
)
from quant_trading.jobs.cancellation import cancel_job_run
from quant_trading.jobs.service import submit_job_run
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobEventORM, JobRunORM
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


class MarketDataSyncRequest(BaseModel):
    provider: str = "akshare"
    symbol: str = Field(min_length=1)
    start: str | None = None
    end: str | None = None


class DataQualityReportRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    candidate_review_id: int | None = Field(default=None, gt=0)
    backtest_run_id: int | None = Field(default=None, gt=0)
    start: str | None = None
    end: str | None = None


class ResearchValidationRequest(BaseModel):
    candidate_review_id: int = Field(gt=0)


class AgentMarketAnalysisRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    start: str | None = None
    end: str | None = None
    lookback_bars: int = Field(default=252, ge=60, le=1000)
    mode: str = Field(default="overview", pattern="^(overview|risk|regime)$")


class AgentStrategyIdeaRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=4000)
    symbol: str | None = Field(default=None, max_length=32)
    market_context: str | None = Field(default=None, max_length=2000)
    constraints: dict[str, Any] = Field(default_factory=dict)


class AgentBacktestReviewRequest(BaseModel):
    candidate_review_id: int = Field(gt=0)
    backtest_run_id: int | None = Field(default=None, gt=0)


@router.post("/import-legacy")
def create_import_job(payload: ImportLegacyRequest, request: Request) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            IMPORT_LEGACY,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )


@router.post("/backtests/ma-cross")
def create_backtest_job(payload: MACrossBacktestRequest, request: Request) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            BACKTEST_MA_CROSS,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )


@router.post("/paper/runs/{run_id}/tick")
def create_paper_tick_job(run_id: int, request: Request) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            PAPER_RUN_TICK,
            {"run_id": run_id},
            make_queue,
        )
    )


@router.post("/market-data/sync")
def create_market_data_sync_job(payload: MarketDataSyncRequest, request: Request) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            MARKET_DATA_SYNC,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )


@router.post("/data-quality/report")
def create_data_quality_report_job(
    payload: DataQualityReportRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            DATA_QUALITY_REPORT,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )


@router.post("/validation/research")
def create_research_validation_job(
    payload: ResearchValidationRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            RESEARCH_VALIDATION,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )


@router.post("/agents/market-analysis")
def create_agent_market_analysis_job(
    payload: AgentMarketAnalysisRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            JOB_AGENT_MARKET_ANALYSIS,
            _agent_job_payload(payload.model_dump(mode="json"), request.app.state.settings),
            make_queue,
        )
    )


@router.post("/agents/strategy-idea")
def create_agent_strategy_idea_job(
    payload: AgentStrategyIdeaRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            JOB_AGENT_STRATEGY_IDEA,
            _agent_job_payload(payload.model_dump(mode="json"), request.app.state.settings),
            make_queue,
        )
    )


@router.post("/agents/backtest-review")
def create_agent_backtest_review_job(
    payload: AgentBacktestReviewRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            JOB_AGENT_BACKTEST_REVIEW,
            _agent_job_payload(payload.model_dump(mode="json"), request.app.state.settings),
            make_queue,
        )
    )


@router.get("")
def list_jobs(
    request: Request,
    status: str | None = None,
    job_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = JobRunRepository(session).list_recent(
            status=status,
            job_type=job_type,
            limit=limit,
        )
        return [_job_payload(row) for row in rows]


@router.post("/{job_run_id}/cancel")
def cancel_job(job_run_id: int, request: Request) -> dict[str, Any]:
    try:
        return _job_payload(cancel_job_run(request.app.state.engine, job_run_id))
    except ValueError as exc:
        message = str(exc)
        if message.startswith("job run not found"):
            raise HTTPException(status_code=404, detail=message) from exc
        if message.startswith("cannot cancel terminal job"):
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc


@router.get("/{job_run_id}/events")
def list_job_events(job_run_id: int, request: Request) -> list[dict[str, Any]]:
    with session_scope(request.app.state.engine) as session:
        if JobRunRepository(session).get(job_run_id) is None:
            raise HTTPException(status_code=404, detail="job run not found")
        return [
            _job_event_payload(row)
            for row in JobEventRepository(session).list_for_job(job_run_id)
        ]


@router.get("/{job_run_id}/stream")
def stream_job_events(
    job_run_id: int,
    request: Request,
    after_event_id: int = 0,
    poll_interval_seconds: float = 1.0,
    heartbeat_seconds: float = 15.0,
    max_idle_seconds: float | None = None,
) -> StreamingResponse:
    ensure_job_exists(request.app.state.engine, job_run_id)
    return StreamingResponse(
        iter_job_event_sse(
            request,
            request.app.state.engine,
            job_run_id,
            after_event_id=after_event_id,
            poll_interval_seconds=poll_interval_seconds,
            heartbeat_seconds=heartbeat_seconds,
            max_idle_seconds=max_idle_seconds,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/{job_run_id}")
def get_job(job_run_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = JobRunRepository(session).get(job_run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="job run not found")
        return _job_payload(row)


def _job_payload(row: JobRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_type": row.job_type,
        "status": row.status,
        "progress": row.progress,
        "request_payload": _json_loads(row.request_payload),
        "result_payload": _json_loads(row.result_payload),
        "error_message": row.error_message,
        "workflow_run_id": row.workflow_run_id,
        "rq_job_id": row.rq_job_id,
        "queued_at": _iso(row.queued_at),
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _job_event_payload(row: JobEventORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_run_id": row.job_run_id,
        "event_type": row.event_type,
        "message": row.message,
        "progress": row.progress,
        "payload": _json_loads(row.payload),
        "created_at": _iso(row.created_at),
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _agent_job_payload(payload: dict[str, Any], settings) -> dict[str, Any]:
    return {
        **payload,
        "deepseek_api_base": settings.deepseek_api_base,
        "deepseek_model": settings.deepseek_model,
        "agent_prompt_max_chars": settings.agent_prompt_max_chars,
        "agent_result_max_chars": settings.agent_result_max_chars,
    }


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
