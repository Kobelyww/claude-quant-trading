from datetime import UTC, datetime, timedelta
import json

from quant_trading.jobs.runtime import MARKET_DATA_SYNC, job_payload_dumps
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobScheduleORM
from quant_trading.storage.repositories import JobScheduleRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_job_schedule_repository_creates_filters_and_advances_schedule():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        row = repo.create(
            name="daily-000001-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload=job_payload_dumps({"provider": "fake", "symbol": "000001"}),
            schedule_type="interval",
            interval_seconds=86400,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )
        repo.mark_submitted(row, job_run_id=7, ran_at=now, next_run_at=now + timedelta(days=1))

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        due = repo.list_due(now + timedelta(hours=1))
        filtered = repo.list_recent(enabled=True, job_type=MARKET_DATA_SYNC)
        row = session.get(JobScheduleORM, 1)

        assert due == []
        assert [schedule.name for schedule in filtered] == ["daily-000001-sync"]
        assert row.last_job_run_id == 7
        assert row.next_run_at == now + timedelta(days=1)
        assert json.loads(row.request_payload) == {"provider": "fake", "symbol": "000001"}


def test_job_schedule_repository_can_disable_and_get_by_name():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        row = repo.create(
            name="disabled-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload="{}",
            schedule_type="interval",
            interval_seconds=3600,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )
        repo.update(row, enabled=False, updated_at=now)

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        assert repo.get_by_name("disabled-sync").enabled is False
        assert repo.list_due(now) == []


def test_job_schedule_repository_acquires_and_blocks_active_lease():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        repo.create(
            name="leased-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload="{}",
            schedule_type="interval",
            interval_seconds=3600,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        assert (
            repo.acquire_due_lease(
                1,
                now=now,
                lease_until=now + timedelta(minutes=5),
                locked_by="runner-a",
            )
            is True
        )
        row = repo.get(1)
        assert row.locked_by == "runner-a"
        assert row.lock_acquired_at == now
        assert row.locked_until == now + timedelta(minutes=5)

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        assert (
            repo.acquire_due_lease(
                1,
                now=now,
                lease_until=now + timedelta(minutes=5),
                locked_by="runner-b",
            )
            is False
        )


def test_job_schedule_repository_reclaims_expired_lease_and_clears_on_submit():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        row = repo.create(
            name="expired-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload="{}",
            schedule_type="interval",
            interval_seconds=3600,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )
        row.locked_until = now - timedelta(seconds=1)
        row.locked_by = "dead-runner"
        row.lock_acquired_at = now - timedelta(minutes=10)
        session.flush()

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        assert (
            repo.acquire_due_lease(
                1,
                now=now,
                lease_until=now + timedelta(minutes=5),
                locked_by="runner-c",
            )
            is True
        )
        row = repo.get(1)
        repo.mark_submitted(row, job_run_id=42, ran_at=now, next_run_at=now + timedelta(hours=1))
        assert row.locked_until is None
        assert row.locked_by is None
        assert row.lock_acquired_at is None
