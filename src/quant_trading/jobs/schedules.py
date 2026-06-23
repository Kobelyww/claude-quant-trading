from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any

from sqlalchemy import Engine

from quant_trading.config import AppSettings
from quant_trading.jobs.runtime import MARKET_DATA_SYNC, job_payload_dumps
from quant_trading.jobs.service import submit_job_run
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobScheduleORM
from quant_trading.storage.repositories import JobScheduleRepository

SUPPORTED_SCHEDULE_JOB_TYPES = {MARKET_DATA_SYNC}


def create_job_schedule(
    engine: Engine,
    name: str,
    job_type: str,
    request_payload: dict[str, Any],
    interval_seconds: int,
    next_run_at: datetime,
    *,
    enabled: bool = True,
) -> JobScheduleORM:
    _validate_schedule(job_type, request_payload, interval_seconds)
    now = _utcnow()
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        if repo.get_by_name(name) is not None:
            raise ValueError(f"job schedule already exists: {name}")
        row = repo.create(
            name,
            job_type,
            job_payload_dumps(request_payload),
            "interval",
            interval_seconds,
            enabled,
            next_run_at,
            now,
        )
        session.expunge(row)
        return row


def update_job_schedule(
    engine: Engine,
    schedule_id: int,
    *,
    enabled: bool | None = None,
    request_payload: dict[str, Any] | None = None,
    interval_seconds: int | None = None,
    next_run_at: datetime | None = None,
) -> JobScheduleORM:
    now = _utcnow()
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        row = repo.get(schedule_id)
        if row is None:
            raise ValueError(f"job schedule not found: {schedule_id}")
        payload_text = None
        if request_payload is not None:
            _validate_payload(request_payload)
            payload_text = job_payload_dumps(request_payload)
        if interval_seconds is not None and interval_seconds < 60:
            raise ValueError("interval_seconds must be at least 60")
        repo.update(
            row,
            enabled=enabled,
            request_payload=payload_text,
            interval_seconds=interval_seconds,
            next_run_at=next_run_at,
            updated_at=now,
        )
        session.expunge(row)
        return row


def run_due_schedules(
    engine: Engine,
    settings: AppSettings,
    now: datetime,
    queue_factory,
) -> list[dict[str, Any]]:
    with session_scope(engine) as session:
        due_ids = [row.id for row in JobScheduleRepository(session).list_due(now)]

    submitted: list[dict[str, Any]] = []
    for schedule_id in due_ids:
        with session_scope(engine) as session:
            repo = JobScheduleRepository(session)
            schedule = repo.get(schedule_id)
            if schedule is None or not schedule.enabled or schedule.next_run_at > now:
                continue
            payload = _loads_payload(schedule.request_payload)
            next_run_at = _advance_interval(
                schedule.next_run_at,
                schedule.interval_seconds,
                now,
            )
            schedule_name = schedule.name
            job_type = schedule.job_type

        row = submit_job_run(engine, settings, job_type, payload, queue_factory)
        with session_scope(engine) as session:
            repo = JobScheduleRepository(session)
            schedule = repo.get(schedule_id)
            if schedule is not None:
                repo.mark_submitted(schedule, row.id, ran_at=now, next_run_at=next_run_at)
        submitted.append(
            {
                "schedule_id": schedule_id,
                "schedule_name": schedule_name,
                "job_run_id": row.id,
            }
        )
    return submitted


def _validate_schedule(
    job_type: str,
    request_payload: dict[str, Any],
    interval_seconds: int,
) -> None:
    if job_type not in SUPPORTED_SCHEDULE_JOB_TYPES:
        raise ValueError(f"unsupported schedule job_type: {job_type}")
    _validate_payload(request_payload)
    if interval_seconds < 60:
        raise ValueError("interval_seconds must be at least 60")


def _validate_payload(request_payload: dict[str, Any]) -> None:
    if not isinstance(request_payload, dict):
        raise ValueError("request_payload must be an object")


def _loads_payload(value: str) -> dict[str, Any]:
    loaded = json.loads(value or "{}")
    if not isinstance(loaded, dict):
        raise ValueError("request_payload must be an object")
    return loaded


def _advance_interval(next_run_at: datetime, interval_seconds: int, now: datetime) -> datetime:
    advanced = next_run_at
    step = timedelta(seconds=interval_seconds)
    while advanced <= now:
        advanced += step
    return advanced


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
