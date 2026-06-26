from datetime import date, datetime

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import DataQualityReportRepository


def test_data_quality_report_repository_lifecycle_and_filters():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    started = datetime(2026, 6, 26, 9, 0, 0)
    finished = datetime(2026, 6, 26, 9, 0, 1)

    with session_scope(engine) as session:
        repo = DataQualityReportRepository(session)
        row = repo.create_running(
            candidate_review_id=None,
            backtest_run_id=None,
            job_run_id=None,
            symbol="000001",
            source="akshare",
            adjusted="qfq",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            created_at=started,
        )
        repo.mark_completed(
            row,
            status="passed",
            severity="none",
            bar_count=260,
            expected_bar_count=260,
            missing_bar_count=0,
            duplicate_timestamp_count=0,
            non_positive_price_count=0,
            non_positive_volume_count=0,
            invalid_ohlc_count=0,
            stale_data=False,
            data_fingerprint="a" * 64,
            findings_payload='{"checks":[]}',
            finished_at=finished,
            duration_ms=1000,
        )
        row_id = row.id

    with session_scope(engine) as session:
        repo = DataQualityReportRepository(session)
        row = repo.get(row_id)
        assert row is not None
        assert row.status == "passed"
        assert row.severity == "none"
        assert row.symbol == "000001"
        assert row.bar_count == 260
        assert row.data_fingerprint == "a" * 64
        assert repo.get(row.id).id == row.id
        assert [item.id for item in repo.list_recent(symbol="000001")] == [row.id]
        assert [item.id for item in repo.list_recent(status="passed")] == [row.id]
        assert [item.id for item in repo.list_recent(severity="none")] == [row.id]


def test_data_quality_report_repository_marks_failed_with_capped_error():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    started = datetime(2026, 6, 26, 9, 0, 0)
    finished = datetime(2026, 6, 26, 9, 0, 1)

    with session_scope(engine) as session:
        repo = DataQualityReportRepository(session)
        row = repo.create_running(
            candidate_review_id=None,
            backtest_run_id=None,
            job_run_id=None,
            symbol="000001",
            source="akshare",
            adjusted="qfq",
            start_date=None,
            end_date=None,
            created_at=started,
        )
        repo.mark_failed(row, "x" * 1200, finished_at=finished, duration_ms=1000)
        row_id = row.id

    with session_scope(engine) as session:
        row = DataQualityReportRepository(session).get(row_id)
        assert row is not None
        assert row.status == "failed"
        assert row.severity == "high"
        assert row.duration_ms == 1000
        assert row.error_message == "x" * 1000
