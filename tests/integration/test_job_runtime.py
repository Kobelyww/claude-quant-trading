import json
from pathlib import Path

import pytest
from sqlalchemy import select

from quant_trading.jobs.runtime import (
    BACKTEST_MA_CROSS,
    IMPORT_LEGACY,
    execute_job_run_with_engine,
    job_payload_dumps,
    utcnow,
)
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobRunORM, WorkflowRunORM
from quant_trading.storage.repositories import JobRunRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def create_job(engine, job_type: str, payload: dict) -> int:
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(
            job_type=job_type,
            request_payload=job_payload_dumps(payload),
            queued_at=utcnow(),
        )
        return row.id


def get_job(engine, job_run_id: int) -> JobRunORM:
    with session_scope(engine) as session:
        return session.get(JobRunORM, job_run_id)


def test_execute_import_job_records_success_and_workflow_run(legacy_sqlite_db: Path):
    engine = make_engine_with_schema()
    job_run_id = create_job(engine, IMPORT_LEGACY, {"legacy_db_path": str(legacy_sqlite_db)})

    result = execute_job_run_with_engine(engine, job_run_id)

    job = get_job(engine, job_run_id)
    assert result["job_run_id"] == job_run_id
    assert job.status == "succeeded"
    assert job.progress == 100
    assert job.workflow_run_id == 1
    assert json.loads(job.result_payload) == {"imported_bars": 121, "imported_symbols": 1}
    with session_scope(engine) as session:
        workflow = session.scalar(select(WorkflowRunORM))
        assert workflow.command_name == IMPORT_LEGACY
        assert workflow.status == "succeeded"


def test_execute_backtest_job_failure_marks_job_failed(legacy_sqlite_db: Path):
    engine = make_engine_with_schema()
    import_job_id = create_job(engine, IMPORT_LEGACY, {"legacy_db_path": str(legacy_sqlite_db)})
    execute_job_run_with_engine(engine, import_job_id)
    job_run_id = create_job(
        engine,
        BACKTEST_MA_CROSS,
        {
            "symbol": "NO_SUCH",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
            "initial_cash": "100000",
        },
    )

    result = execute_job_run_with_engine(engine, job_run_id)

    job = get_job(engine, job_run_id)
    assert result["status"] == "failed"
    assert job.status == "failed"
    assert "no market bars found" in job.error_message
    assert json.loads(job.result_payload) == {}


def test_execute_unknown_job_id_raises_value_error():
    engine = make_engine_with_schema()

    with pytest.raises(ValueError, match="job run not found: 99"):
        execute_job_run_with_engine(engine, 99)


def test_execute_unsupported_job_type_marks_failed():
    engine = make_engine_with_schema()
    job_run_id = create_job(engine, "not_supported", {})

    result = execute_job_run_with_engine(engine, job_run_id)

    job = get_job(engine, job_run_id)
    assert result["status"] == "failed"
    assert job.status == "failed"
    assert "unsupported job type" in job.error_message
