from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _inspector(database_url: str):
    engine = create_engine(database_url, future=True)
    return inspect(engine)


def _columns(inspector, table_name: str) -> dict[str, dict]:
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _index_columns(inspector, table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(table_name)
    }


def _unique_columns(inspector, table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
    }


def _default_text(column: dict) -> str:
    return str(column.get("default") or "").strip("'\"")


def _assert_validation_report_schema(inspector) -> None:
    candidate_review_columns = _columns(inspector, "agent_candidate_reviews")
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
    } <= set(candidate_review_columns)
    assert candidate_review_columns["data_quality_report_id"]["nullable"] is True
    assert candidate_review_columns["research_validation_report_id"]["nullable"] is True

    candidate_review_indexes = _index_columns(inspector, "agent_candidate_reviews")
    assert (
        candidate_review_indexes["ix_agent_candidate_reviews_data_quality_report_id"]
        == ("data_quality_report_id",)
    )
    assert (
        candidate_review_indexes[
            "ix_agent_candidate_reviews_research_validation_report_id"
        ]
        == ("research_validation_report_id",)
    )

    data_quality_report_columns = _columns(inspector, "data_quality_reports")
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
    } <= set(data_quality_report_columns)
    assert data_quality_report_columns["symbol"]["nullable"] is False
    assert data_quality_report_columns["source"]["nullable"] is False
    assert data_quality_report_columns["adjusted"]["nullable"] is False
    assert data_quality_report_columns["findings_payload"]["nullable"] is False
    assert data_quality_report_columns["error_message"]["nullable"] is True
    assert _default_text(data_quality_report_columns["source"]) == ""
    assert _default_text(data_quality_report_columns["adjusted"]) == ""
    assert _default_text(data_quality_report_columns["bar_count"]) == "0"
    assert _default_text(data_quality_report_columns["expected_bar_count"]) == "0"
    assert _default_text(data_quality_report_columns["missing_bar_count"]) == "0"
    assert _default_text(data_quality_report_columns["status"]) == "running"
    assert _default_text(data_quality_report_columns["severity"]) == "unknown"
    assert _default_text(data_quality_report_columns["findings_payload"]) == "{}"

    data_quality_indexes = _index_columns(inspector, "data_quality_reports")
    assert data_quality_indexes["ix_data_quality_reports_candidate_review_id"] == (
        "candidate_review_id",
    )
    assert data_quality_indexes["ix_data_quality_reports_backtest_run_id"] == (
        "backtest_run_id",
    )
    assert data_quality_indexes["ix_data_quality_reports_job_run_id"] == (
        "job_run_id",
    )
    assert data_quality_indexes["ix_data_quality_reports_symbol"] == ("symbol",)
    assert data_quality_indexes["ix_data_quality_reports_status"] == ("status",)
    assert data_quality_indexes["ix_data_quality_reports_severity"] == ("severity",)
    assert data_quality_indexes["ix_data_quality_reports_symbol_start_date_end_date"] == (
        "symbol",
        "start_date",
        "end_date",
    )

    research_validation_report_columns = _columns(
        inspector, "research_validation_reports"
    )
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
    } <= set(research_validation_report_columns)
    assert research_validation_report_columns["candidate_review_id"]["nullable"] is False
    assert research_validation_report_columns["data_quality_report_id"]["nullable"] is True
    assert research_validation_report_columns["job_run_id"]["nullable"] is True
    assert research_validation_report_columns["validation_status"]["nullable"] is False
    assert research_validation_report_columns["readiness_floor"]["nullable"] is False
    assert research_validation_report_columns["error_message"]["nullable"] is True
    assert _default_text(
        research_validation_report_columns["validation_status"]
    ) == "running"
    assert _default_text(
        research_validation_report_columns["readiness_floor"]
    ) == "not_ready"
    for payload_column in [
        "in_sample_metrics_payload",
        "out_of_sample_metrics_payload",
        "walk_forward_payload",
        "parameter_sensitivity_payload",
        "benchmark_payload",
        "summary_payload",
    ]:
        assert research_validation_report_columns[payload_column]["nullable"] is False
        assert _default_text(research_validation_report_columns[payload_column]) == "{}"

    research_validation_indexes = _index_columns(
        inspector, "research_validation_reports"
    )
    assert research_validation_indexes[
        "ix_research_validation_reports_candidate_review_id"
    ] == ("candidate_review_id",)
    assert research_validation_indexes[
        "ix_research_validation_reports_source_backtest_run_id"
    ] == ("source_backtest_run_id",)
    assert research_validation_indexes[
        "ix_research_validation_reports_data_quality_report_id"
    ] == ("data_quality_report_id",)
    assert research_validation_indexes["ix_research_validation_reports_job_run_id"] == (
        "job_run_id",
    )
    assert research_validation_indexes["ix_research_validation_reports_symbol"] == (
        "symbol",
    )
    assert research_validation_indexes[
        "ix_research_validation_reports_strategy_name"
    ] == ("strategy_name",)
    assert research_validation_indexes[
        "ix_research_validation_reports_validation_status"
    ] == ("validation_status",)

    research_validation_uniques = _unique_columns(
        inspector, "research_validation_reports"
    )
    assert research_validation_uniques[
        "uq_research_validation_reports_candidate_review_id"
    ] == ("candidate_review_id",)


def test_alembic_upgrade_head_creates_runtime_schema(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "runtime.sqlite3"
    database_url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    inspector = _inspector(database_url)
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

    _assert_validation_report_schema(inspector)


def test_validation_report_migration_downgrade_and_reupgrade(
    tmp_path: Path, monkeypatch
):
    db_path = tmp_path / "runtime.sqlite3"
    database_url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")
    _assert_validation_report_schema(_inspector(database_url))

    command.downgrade(config, "20260624_0008")
    downgraded_inspector = _inspector(database_url)
    downgraded_tables = set(downgraded_inspector.get_table_names())
    assert "data_quality_reports" not in downgraded_tables
    assert "research_validation_reports" not in downgraded_tables
    downgraded_candidate_columns = _columns(
        downgraded_inspector, "agent_candidate_reviews"
    )
    assert "data_quality_report_id" not in downgraded_candidate_columns
    assert "research_validation_report_id" not in downgraded_candidate_columns

    command.upgrade(config, "head")
    reupgraded_inspector = _inspector(database_url)
    reupgraded_tables = set(reupgraded_inspector.get_table_names())
    assert "data_quality_reports" in reupgraded_tables
    assert "research_validation_reports" in reupgraded_tables
    _assert_validation_report_schema(reupgraded_inspector)
