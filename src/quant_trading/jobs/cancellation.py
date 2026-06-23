from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobRunORM
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class JobCancelled(Exception):
    pass


class CancellationToken:
    def __init__(self, engine: Engine, job_run_id: int | None):
        self.engine = engine
        self.job_run_id = job_run_id

    def raise_if_cancelled(self) -> None:
        if self.job_run_id is None:
            return
        with session_scope(self.engine) as session:
            row = JobRunRepository(session).get(self.job_run_id)
            if row is not None and row.status in {"cancel_requested", "cancelled"}:
                raise JobCancelled("cancelled")


def cancel_job_run(engine: Engine, job_run_id: int) -> JobRunORM:
    now = _utcnow()
    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        events = JobEventRepository(session)
        row = repo.get(job_run_id)
        if row is None:
            raise ValueError(f"job run not found: {job_run_id}")
        if row.status in TERMINAL_STATUSES:
            raise ValueError(f"cannot cancel terminal job: {row.status}")
        if row.status == "queued":
            repo.mark_cancelled(row, finished_at=now)
            events.record(
                row.id,
                "cancelled",
                "job cancelled before execution",
                progress=row.progress,
                created_at=now,
            )
        else:
            repo.mark_cancel_requested(row, updated_at=now)
            events.record(
                row.id,
                "cancel_requested",
                "cancellation requested",
                progress=row.progress,
                created_at=now,
            )
        session.expunge(row)
        return row


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
