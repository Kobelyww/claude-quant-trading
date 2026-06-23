from datetime import UTC, date, datetime

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import DataSyncRunORM
from quant_trading.storage.repositories import DataSyncRunRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_data_sync_run_repository_lifecycle_records_success():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)

    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        row = repo.create_running(
            provider="akshare",
            symbol="000001",
            market="a_stock",
            asset_type="stock",
            currency="CNY",
            exchange="SZSE",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            job_run_id=9,
            started_at=now,
        )
        repo.mark_succeeded(row, imported_bars=3, finished_at=now, duration_ms=12)

    with session_scope(engine) as session:
        row = session.get(DataSyncRunORM, 1)
        assert row is not None
        assert row.provider == "akshare"
        assert row.symbol == "000001"
        assert row.status == "succeeded"
        assert row.imported_bars == 3
        assert row.job_run_id == 9
        assert row.error_message is None
        assert row.finished_at is not None
        assert row.duration_ms == 12


def test_data_sync_run_repository_filters_recent_rows_and_records_failure():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)

    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        first = repo.create_running(
            "akshare", "000001", "a_stock", "stock", "CNY", "SZSE", None, None, None, now
        )
        second = repo.create_running(
            "akshare", "600000", "a_stock", "stock", "CNY", "SSE", None, None, None, now
        )
        repo.mark_failed(first, "provider unavailable", now, 4)
        repo.mark_succeeded(second, imported_bars=0, finished_at=now, duration_ms=5)

    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        failed = repo.list_recent(status="failed")
        symbol_rows = repo.list_recent(symbol="600000")
        provider_rows = repo.list_recent(provider="akshare", limit=1)

        assert [row.symbol for row in failed] == ["000001"]
        assert [row.status for row in symbol_rows] == ["succeeded"]
        assert [row.symbol for row in provider_rows] == ["600000"]
        assert repo.get(2).exchange == "SSE"
