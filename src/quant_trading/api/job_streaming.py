from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime
import json
import time
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import Engine

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobEventORM
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository

TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


def ensure_job_exists(engine: Engine, job_run_id: int) -> None:
    with session_scope(engine) as session:
        if JobRunRepository(session).get(job_run_id) is None:
            raise HTTPException(status_code=404, detail="job run not found")


async def iter_job_event_sse(
    request: Request,
    engine: Engine,
    job_run_id: int,
    *,
    after_event_id: int = 0,
    poll_interval_seconds: float = 1.0,
    heartbeat_seconds: float = 15.0,
    max_idle_seconds: float | None = None,
) -> AsyncIterator[str]:
    last_event_id = max(0, after_event_id)
    poll_interval = _clamp(poll_interval_seconds, minimum=0.001, maximum=5.0)
    heartbeat_interval = _clamp(heartbeat_seconds, minimum=0.001, maximum=60.0)
    idle_limit = (
        None
        if max_idle_seconds is None
        else _clamp(max_idle_seconds, minimum=0.001, maximum=300.0)
    )
    last_emit_at = time.monotonic()
    idle_started_at = last_emit_at

    while True:
        if await request.is_disconnected():
            break

        events, status = _load_events_and_status(engine, job_run_id, last_event_id)
        emitted_event = False
        for event in events:
            last_event_id = event.id
            emitted_event = True
            last_emit_at = time.monotonic()
            yield format_sse("job_event", _job_event_payload(event), event_id=event.id)

        if emitted_event:
            idle_started_at = time.monotonic()

        if status in TERMINAL_JOB_STATUSES:
            yield format_sse("stream_end", {"job_run_id": job_run_id, "status": status})
            break

        now = time.monotonic()
        if now - last_emit_at >= heartbeat_interval:
            yield format_sse("heartbeat", {})
            last_emit_at = now

        if idle_limit is not None and now - idle_started_at >= idle_limit:
            break

        await asyncio.sleep(poll_interval)


def format_sse(event_name: str, data: dict[str, Any], *, event_id: int | None = None) -> str:
    lines = [f"event: {event_name}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
    for line in encoded.splitlines() or ["{}"]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _load_events_and_status(
    engine: Engine,
    job_run_id: int,
    after_event_id: int,
) -> tuple[list[JobEventORM], str | None]:
    with session_scope(engine) as session:
        job = JobRunRepository(session).get(job_run_id)
        if job is None:
            return [], None
        events = JobEventRepository(session).list_for_job(
            job_run_id,
            after_event_id=after_event_id,
        )
        return events, job.status


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


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)
