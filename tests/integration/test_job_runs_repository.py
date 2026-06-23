import json
from datetime import UTC, datetime

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobRunORM
from quant_trading.storage.repositories import JobRunRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_job_run_repository_lifecycle_records_status_and_payloads():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)

    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        row = repo.create_queued(
            job_type="backtest_ma_cross",
            request_payload='{"symbol": "000001"}',
            queued_at=now,
        )
        repo.mark_running(row, started_at=now)
        repo.mark_succeeded(
            row,
            result_payload='{"run_id": 7}',
            workflow_run_id=3,
            finished_at=now,
            duration_ms=25,
        )

    with session_scope(engine) as session:
        row = session.get(JobRunORM, 1)
        assert row is not None
        assert row.job_type == "backtest_ma_cross"
        assert row.status == "succeeded"
        assert row.progress == 100
        assert json.loads(row.request_payload) == {"symbol": "000001"}
        assert json.loads(row.result_payload) == {"run_id": 7}
        assert row.workflow_run_id == 3
        assert row.duration_ms == 25
        assert row.started_at is not None
        assert row.finished_at is not None


def test_job_run_repository_filters_recent_rows():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)

    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        first = repo.create_queued("import_legacy", "{}", now)
        second = repo.create_queued("paper_run_tick", "{}", now)
        repo.mark_failed(first, "bad input", now, 10)
        repo.mark_enqueued(second, rq_job_id="rq-123", updated_at=now)

    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        failed = repo.list_recent(status="failed")
        tick = repo.list_recent(job_type="paper_run_tick")

        assert [row.job_type for row in failed] == ["import_legacy"]
        assert [row.rq_job_id for row in tick] == ["rq-123"]
        assert repo.get(2).job_type == "paper_run_tick"
