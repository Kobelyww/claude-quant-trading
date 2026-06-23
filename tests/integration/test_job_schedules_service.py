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
