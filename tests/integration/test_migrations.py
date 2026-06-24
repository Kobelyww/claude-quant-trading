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
        "error_message",
        "created_at",
        "updated_at",
        "decided_at",
    } <= candidate_review_columns
