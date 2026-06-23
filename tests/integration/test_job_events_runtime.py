from datetime import date
from decimal import Decimal

import pytest

from quant_trading.config import AppSettings
from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.data.providers.registry import ProviderRegistry
from quant_trading.data.sync import sync_daily_market_data
from quant_trading.jobs.cancellation import JobCancelled, cancel_job_run
from quant_trading.jobs.runtime import (
    IMPORT_LEGACY,
    MARKET_DATA_SYNC,
    execute_job_run_with_engine,
    job_payload_dumps,
    utcnow,
)
from quant_trading.jobs.service import submit_job_run
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository


class FakeQueueJob:
    id = "rq-1"


class FakeQueue:
    def enqueue(self, func, *args):
        return FakeQueueJob()


class FakeProvider:
    name = "fake"

    def fetch_daily_bars(self, instrument_id, symbol, start, end):
        return [
            Bar(
                instrument_id=instrument_id,
                symbol=symbol,
                market=Market.A_STOCK,
                timestamp=date(2026, 6, 22),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                volume=Decimal("1000"),
                source="fake",
            )
        ]


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_submit_job_records_queued_and_enqueued_events():
    engine = make_engine_with_schema()
    row = submit_job_run(
        engine,
        AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"),
        IMPORT_LEGACY,
        {"legacy_db_path": "legacy.sqlite3"},
        lambda url: FakeQueue(),
    )

    with session_scope(engine) as session:
        events = JobEventRepository(session).list_for_job(row.id)
        assert [event.event_type for event in events] == ["queued", "enqueued"]
        assert events[1].payload == '{"rq_job_id": "rq-1"}'


def test_cancel_queued_job_records_cancelled_event():
    engine = make_engine_with_schema()
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(IMPORT_LEGACY, "{}", utcnow())
        job_run_id = row.id

    cancelled = cancel_job_run(engine, job_run_id)

    assert cancelled.status == "cancelled"
    with session_scope(engine) as session:
        events = JobEventRepository(session).list_for_job(job_run_id)
        assert [event.event_type for event in events] == ["cancelled"]


def test_execute_job_skips_pre_cancelled_job():
    engine = make_engine_with_schema()
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(
            IMPORT_LEGACY,
            job_payload_dumps({"legacy_db_path": "missing.sqlite3"}),
            utcnow(),
        )
        JobRunRepository(session).mark_cancelled(row, utcnow())
        job_run_id = row.id

    result = execute_job_run_with_engine(engine, job_run_id)

    assert result == {
        "job_run_id": job_run_id,
        "status": "cancelled",
        "error_message": "cancelled",
    }


def test_market_sync_checks_cancellation_before_upsert():
    engine = make_engine_with_schema()
    registry = ProviderRegistry([FakeProvider()])
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(MARKET_DATA_SYNC, "{}", utcnow())
        JobRunRepository(session).mark_cancel_requested(row, utcnow())
        job_run_id = row.id

    with pytest.raises(JobCancelled):
        sync_daily_market_data(
            engine,
            provider_name="fake",
            symbol="000001",
            start="2026-06-22",
            end="2026-06-22",
            registry=registry,
            job_run_id=job_run_id,
        )
