from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy import Engine

from quant_trading.config import AppSettings
from quant_trading.jobs.runtime import (
    execute_job_run,
    execute_job_run_with_engine,
    job_payload_dumps,
    utcnow,
)
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobRunORM
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository


class QueueLike(Protocol):
    def enqueue(self, func: Callable[..., object], *args: object) -> object:
        ...


def submit_job_run(
    engine: Engine,
    settings: AppSettings,
    job_type: str,
    request_payload: dict[str, Any],
    queue_factory: Callable[[str], QueueLike],
) -> JobRunORM:
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(
            job_type=job_type,
            request_payload=job_payload_dumps(request_payload),
            queued_at=utcnow(),
        )
        JobEventRepository(session).record(
            row.id,
            "queued",
            "job queued",
            progress=0,
            payload={"job_type": job_type},
            created_at=utcnow(),
        )
        job_run_id = row.id

    if settings.job_executor == "inline":
        execute_job_run_with_engine(engine, job_run_id)
    elif settings.job_executor == "rq":
        queue = queue_factory(settings.redis_url)
        rq_job = queue.enqueue(execute_job_run, settings.database_url, job_run_id)
        with session_scope(engine) as session:
            repo = JobRunRepository(session)
            row = repo.get(job_run_id)
            if row is not None:
                repo.mark_enqueued(row, rq_job_id=str(rq_job.id), updated_at=utcnow())
                JobEventRepository(session).record(
                    row.id,
                    "enqueued",
                    "job enqueued",
                    progress=row.progress,
                    payload={"rq_job_id": str(rq_job.id)},
                    created_at=utcnow(),
                )
    else:
        raise ValueError(f"unsupported job executor: {settings.job_executor}")

    with session_scope(engine) as session:
        row = JobRunRepository(session).get(job_run_id)
        if row is None:
            raise ValueError(f"job run not found after submit: {job_run_id}")
        session.expunge(row)
        return row
