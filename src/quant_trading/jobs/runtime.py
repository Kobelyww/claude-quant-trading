from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
import time
from typing import Any

from sqlalchemy import Engine

from quant_trading.storage.db import make_engine, session_scope
from quant_trading.storage.repositories import JobRunRepository
from quant_trading.workflows.operations import (
    import_legacy_data,
    run_ma_cross_backtest,
    run_paper_tick,
)
from quant_trading.workflows.runner import WorkflowCommandRunner, workflow_payload_dumps

IMPORT_LEGACY = "import_legacy"
BACKTEST_MA_CROSS = "backtest_ma_cross"
PAPER_RUN_TICK = "paper_run_tick"
SUPPORTED_JOB_TYPES = {IMPORT_LEGACY, BACKTEST_MA_CROSS, PAPER_RUN_TICK}


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
        repo.mark_running(job, started_at=started_at)
        job_type = job.job_type
        request_payload = _json_loads(job.request_payload)

    try:
        if job_type not in SUPPORTED_JOB_TYPES:
            raise ValueError(f"unsupported job type: {job_type}")
        execution = WorkflowCommandRunner(engine).run_with_audit(
            job_type,
            request_payload,
            lambda: _execute_payload(engine, job_type, request_payload),
        )
    except Exception as exc:
        finished_at = utcnow()
        duration_ms = _duration_ms(started_counter)
        error_message = _sanitize_error(exc)
        with session_scope(engine) as session:
            repo = JobRunRepository(session)
            job = repo.get(job_run_id)
            if job is not None:
                repo.mark_failed(job, error_message, finished_at, duration_ms)
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
    return {"job_run_id": job_run_id, "status": "succeeded", "result": result_payload}


def job_payload_dumps(payload: dict[str, Any]) -> str:
    return workflow_payload_dumps(payload)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _execute_payload(engine: Engine, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if job_type == IMPORT_LEGACY:
        return import_legacy_data(engine, str(payload["legacy_db_path"]))
    if job_type == BACKTEST_MA_CROSS:
        return run_ma_cross_backtest(
            engine,
            symbol=str(payload["symbol"]),
            short_window=int(payload["short_window"]),
            long_window=int(payload["long_window"]),
            order_size=int(payload["order_size"]),
            initial_cash=Decimal(str(payload["initial_cash"])),
        )
    if job_type == PAPER_RUN_TICK:
        return run_paper_tick(engine, int(payload["run_id"]))
    raise ValueError(f"unsupported job type: {job_type}")


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("job payload must be an object")
    return loaded


def _duration_ms(started_counter: float) -> int:
    return max(0, int((time.perf_counter() - started_counter) * 1000))


def _sanitize_error(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__)[:1000]
