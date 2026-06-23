from __future__ import annotations

from datetime import UTC, date, datetime
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from quant_trading.jobs.queue import make_queue
from quant_trading.jobs.schedules import (
    create_job_schedule,
    run_due_schedules,
    update_job_schedule,
)
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobScheduleORM
from quant_trading.storage.repositories import JobScheduleRepository

router = APIRouter(prefix="/job-schedules", tags=["job-schedules"])


class ScheduleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    job_type: str
    request_payload: dict[str, Any] = Field(default_factory=dict)
    interval_seconds: int
    next_run_at: datetime
    enabled: bool = True


class ScheduleUpdateRequest(BaseModel):
    enabled: bool | None = None
    request_payload: dict[str, Any] | None = None
    interval_seconds: int | None = None
    next_run_at: datetime | None = None


class RunDueRequest(BaseModel):
    now: datetime | None = None


@router.post("")
def create_schedule(payload: ScheduleCreateRequest, request: Request) -> dict[str, Any]:
    try:
        row = create_job_schedule(
            request.app.state.engine,
            name=payload.name,
            job_type=payload.job_type,
            request_payload=payload.request_payload,
            interval_seconds=payload.interval_seconds,
            next_run_at=payload.next_run_at,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _schedule_payload(row)


@router.get("")
def list_schedules(
    request: Request,
    enabled: bool | None = None,
    job_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = JobScheduleRepository(session).list_recent(
            enabled=enabled,
            job_type=job_type,
            limit=limit,
        )
        return [_schedule_payload(row) for row in rows]


@router.post("/run-due")
def run_due(payload: RunDueRequest, request: Request) -> list[dict[str, Any]]:
    now = payload.now or datetime.now(UTC).replace(tzinfo=None)
    return run_due_schedules(
        request.app.state.engine,
        request.app.state.settings,
        now,
        make_queue,
    )


@router.get("/{schedule_id}")
def get_schedule(schedule_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = JobScheduleRepository(session).get(schedule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="job schedule not found")
        return _schedule_payload(row)


@router.patch("/{schedule_id}")
def patch_schedule(
    schedule_id: int,
    payload: ScheduleUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        row = update_job_schedule(
            request.app.state.engine,
            schedule_id,
            **payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("job schedule not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return _schedule_payload(row)


def _schedule_payload(row: JobScheduleORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "job_type": row.job_type,
        "request_payload": _json_loads(row.request_payload),
        "schedule_type": row.schedule_type,
        "interval_seconds": row.interval_seconds,
        "enabled": row.enabled,
        "next_run_at": _iso(row.next_run_at),
        "last_run_at": _iso(row.last_run_at),
        "last_job_run_id": row.last_job_run_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    loaded = json.loads(value or "{}")
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
