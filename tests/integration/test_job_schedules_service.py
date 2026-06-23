from datetime import datetime, timedelta

import pytest

from quant_trading.config import AppSettings
from quant_trading.jobs.runtime import MARKET_DATA_SYNC
from quant_trading.jobs.schedules import create_job_schedule, run_due_schedules
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import JobScheduleRepository


class FakeQueueJob:
    id = "rq-scheduled"


class FakeQueue:
    def enqueue(self, func, *args):
        return FakeQueueJob()


class CountingQueue:
    def __init__(self):
        self.enqueued = 0

    def enqueue(self, func, *args):
        self.enqueued += 1
        return FakeQueueJob()


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_run_due_schedules_submits_once_and_advances_past_now():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    create_job_schedule(
        engine,
        "daily-000001-sync",
        MARKET_DATA_SYNC,
        {"provider": "akshare", "symbol": "000001"},
        3600,
        now - timedelta(hours=3),
    )

    submitted = run_due_schedules(
        engine,
        AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"),
        now,
        lambda url: FakeQueue(),
    )

    assert len(submitted) == 1
    assert submitted[0]["schedule_name"] == "daily-000001-sync"
    with session_scope(engine) as session:
        schedule = JobScheduleRepository(session).get_by_name("daily-000001-sync")
        assert schedule.last_job_run_id == submitted[0]["job_run_id"]
        assert schedule.next_run_at == now + timedelta(hours=1)


def test_schedule_validation_rejects_unknown_job_type_and_short_interval():
    engine = make_engine_with_schema()
    with pytest.raises(ValueError, match="unsupported schedule job_type"):
        create_job_schedule(
            engine,
            "bad-type",
            "paper_run_tick",
            {},
            3600,
            datetime(2026, 6, 23),
        )
    with pytest.raises(ValueError, match="interval_seconds must be at least 60"):
        create_job_schedule(
            engine,
            "too-fast",
            MARKET_DATA_SYNC,
            {},
            30,
            datetime(2026, 6, 23),
        )


def test_run_due_schedules_skips_schedule_with_active_lease():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    create_job_schedule(
        engine,
        "active-lease-sync",
        MARKET_DATA_SYNC,
        {"provider": "akshare", "symbol": "000001"},
        3600,
        now,
    )
    with session_scope(engine) as session:
        schedule = JobScheduleRepository(session).get_by_name("active-lease-sync")
        schedule.locked_until = now + timedelta(minutes=5)
        schedule.locked_by = "runner-a"
        schedule.lock_acquired_at = now
        session.flush()

    queue = CountingQueue()
    submitted = run_due_schedules(
        engine,
        AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"),
        now,
        lambda url: queue,
        scheduler_id="runner-b",
    )

    assert submitted == []
    assert queue.enqueued == 0


def test_run_due_schedules_releases_lease_when_queue_submit_fails():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    create_job_schedule(
        engine,
        "failing-submit-sync",
        MARKET_DATA_SYNC,
        {"provider": "akshare", "symbol": "000001"},
        3600,
        now,
    )

    class FailingQueue:
        def enqueue(self, func, *args):
            raise RuntimeError("queue unavailable")

    with pytest.raises(RuntimeError, match="queue unavailable"):
        run_due_schedules(
            engine,
            AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"),
            now,
            lambda url: FailingQueue(),
            scheduler_id="runner-fail",
            lease_seconds=60,
        )

    with session_scope(engine) as session:
        schedule = JobScheduleRepository(session).get_by_name("failing-submit-sync")
        assert schedule.locked_until is None
        assert schedule.locked_by is None
        assert schedule.lock_acquired_at is None
        assert schedule.last_job_run_id is None
        assert schedule.next_run_at == now
