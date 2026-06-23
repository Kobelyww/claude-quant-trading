from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from quant_trading.api.routes.workflows import ImportLegacyRequest, MACrossBacktestRequest
from quant_trading.jobs.queue import make_queue
from quant_trading.jobs.runtime import (
    BACKTEST_MA_CROSS,
    IMPORT_LEGACY,
    MARKET_DATA_SYNC,
    PAPER_RUN_TICK,
)
from quant_trading.jobs.service import submit_job_run
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobRunORM
from quant_trading.storage.repositories import JobRunRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


class MarketDataSyncRequest(BaseModel):
    provider: str = "akshare"
    symbol: str = Field(min_length=1)
    start: str | None = None
    end: str | None = None


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


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
