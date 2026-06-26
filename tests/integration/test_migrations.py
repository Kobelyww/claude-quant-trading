from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_head_creates_runtime_schema(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "runtime.sqlite3"
    database_url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert "workflow_runs" in tables
    assert "job_runs" in tables
    assert "job_events" in tables
    assert "job_schedules" in tables
    assert "data_sync_runs" in tables
    assert "instruments" in tables
    assert "market_bars" in tables
    assert "backtest_runs" in tables
    assert "paper_accounts" in tables
    assert "paper_runs" in tables
    assert "broker_order_events" in tables
    assert "agent_runs" in tables
    assert "agent_candidate_reviews" in tables
    assert "data_quality_reports" in tables
    assert "research_validation_reports" in tables

    schedule_columns = {column["name"] for column in inspector.get_columns("job_schedules")}
    assert {"locked_until", "locked_by", "lock_acquired_at"} <= schedule_columns

    agent_run_columns = {column["name"] for column in inspector.get_columns("agent_runs")}
    assert {
        "id",
        "agent_type",
        "status",
        "symbol",
        "model_name",
        "request_payload",
        "metrics_payload",
        "result_payload",
        "error_message",
        "job_run_id",
        "started_at",
        "finished_at",
        "duration_ms",
        "created_at",
    } <= agent_run_columns

    candidate_review_columns = {
        column["name"] for column in inspector.get_columns("agent_candidate_reviews")
    }
    assert {
        "id",
        "source_agent_run_id",
        "status",
        "symbol",
        "strategy_name",
        "candidate_payload",
        "backtest_request_payload",
        "operator",
        "operator_note",
        "backtest_job_run_id",
        "backtest_run_id",
        "review_agent_run_id",
        "data_quality_report_id",
        "research_validation_report_id",
        "error_message",
        "created_at",
        "updated_at",
        "decided_at",
    } <= candidate_review_columns

    data_quality_report_columns = {
        column["name"] for column in inspector.get_columns("data_quality_reports")
    }
    assert {
        "id",
        "candidate_review_id",
        "backtest_run_id",
        "job_run_id",
        "symbol",
        "source",
        "adjusted",
        "start_date",
        "end_date",
        "bar_count",
        "expected_bar_count",
        "missing_bar_count",
        "duplicate_timestamp_count",
        "non_positive_price_count",
        "non_positive_volume_count",
        "invalid_ohlc_count",
        "stale_data",
        "data_fingerprint",
        "status",
        "severity",
        "findings_payload",
        "error_message",
        "created_at",
        "finished_at",
        "duration_ms",
    } <= data_quality_report_columns

    research_validation_report_columns = {
        column["name"] for column in inspector.get_columns("research_validation_reports")
    }
    assert {
        "id",
        "candidate_review_id",
        "source_backtest_run_id",
        "data_quality_report_id",
        "job_run_id",
        "symbol",
        "strategy_name",
        "validation_status",
        "readiness_floor",
        "in_sample_metrics_payload",
        "out_of_sample_metrics_payload",
        "walk_forward_payload",
        "parameter_sensitivity_payload",
        "benchmark_payload",
        "summary_payload",
        "error_message",
        "created_at",
        "finished_at",
        "duration_ms",
    } <= research_validation_report_columns
