from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


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


def _index_by_name(inspector, table_name: str, index_name: str) -> dict:
    return next(
        index
        for index in inspector.get_indexes(table_name)
        if index["name"] == index_name
    )


def _default_text(column: dict) -> str:
    return str(column.get("default") or "").strip("'\"")


def _where_text(index: dict) -> str:
    dialect_options = index.get("dialect_options") or {}
    where = dialect_options.get("sqlite_where")
    if where is None:
        where = dialect_options.get("postgresql_where")
    if where is None:
        where = index.get("where")
    if where is None:
        where = ""
    return str(where).lower()


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


def _assert_pre_live_safety_ops_schema(inspector) -> None:
    tables = set(inspector.get_table_names())
    assert {
        "execution_safety_states",
        "execution_order_intents",
        "execution_order_decisions",
        "operator_approval_requests",
        "safety_incidents",
        "kill_switch_events",
    } <= tables

    safety_columns = _columns(inspector, "execution_safety_states")
    assert {
        "id",
        "scope",
        "kill_switch_active",
        "dry_run_enabled",
        "simulated_enabled",
        "live_enabled",
        "reason",
        "updated_by",
        "updated_at",
    } <= set(safety_columns)
    safety_indexes = _index_columns(inspector, "execution_safety_states")
    assert safety_indexes["ix_execution_safety_states_scope"] == ("scope",)
    assert safety_indexes["ix_execution_safety_states_kill_switch_active"] == (
        "kill_switch_active",
    )
    assert safety_indexes["ix_execution_safety_states_dry_run_enabled"] == (
        "dry_run_enabled",
    )
    assert safety_indexes["ix_execution_safety_states_simulated_enabled"] == (
        "simulated_enabled",
    )
    assert safety_indexes["ix_execution_safety_states_live_enabled"] == ("live_enabled",)
    assert safety_indexes["ix_execution_safety_states_updated_at"] == ("updated_at",)
    assert _unique_columns(inspector, "execution_safety_states")[
        "uq_execution_safety_states_scope"
    ] == ("scope",)

    intent_columns = _columns(inspector, "execution_order_intents")
    assert {
        "id",
        "source_type",
        "source_id",
        "paper_run_id",
        "paper_order_id",
        "client_order_id",
        "symbol",
        "instrument_id",
        "side",
        "order_type",
        "quantity",
        "limit_price",
        "estimated_price",
        "estimated_notional",
        "broker_mode",
        "status",
        "risk_profile_name",
        "risk_summary_payload",
        "risk_summary_payload_digest",
        "approval_required",
        "approval_request_id",
        "blocked_reason_code",
        "blocked_reason",
        "created_at",
        "updated_at",
        "submitted_at",
    } <= set(intent_columns)
    assert intent_columns["source_id"]["nullable"] is True
    assert intent_columns["paper_run_id"]["nullable"] is True
    assert intent_columns["paper_order_id"]["nullable"] is True
    assert intent_columns["approval_request_id"]["nullable"] is True
    intent_indexes = _index_columns(inspector, "execution_order_intents")
    for name, columns in {
        "ix_execution_order_intents_source_type": ("source_type",),
        "ix_execution_order_intents_source_id": ("source_id",),
        "ix_execution_order_intents_paper_run_id": ("paper_run_id",),
        "ix_execution_order_intents_paper_order_id": ("paper_order_id",),
        "ix_execution_order_intents_client_order_id": ("client_order_id",),
        "ix_execution_order_intents_symbol": ("symbol",),
        "ix_execution_order_intents_instrument_id": ("instrument_id",),
        "ix_execution_order_intents_broker_mode": ("broker_mode",),
        "ix_execution_order_intents_status": ("status",),
        "ix_execution_order_intents_risk_profile_name": ("risk_profile_name",),
        "ix_execution_order_intents_risk_summary_payload_digest": (
            "risk_summary_payload_digest",
        ),
        "ix_execution_order_intents_approval_required": ("approval_required",),
        "ix_execution_order_intents_approval_request_id": ("approval_request_id",),
        "ix_execution_order_intents_blocked_reason_code": ("blocked_reason_code",),
        "ix_execution_order_intents_created_at": ("created_at",),
        "ix_execution_order_intents_updated_at": ("updated_at",),
        "ix_execution_order_intents_submitted_at": ("submitted_at",),
    }.items():
        assert intent_indexes[name] == columns
    assert _unique_columns(inspector, "execution_order_intents")[
        "uq_execution_order_intents_client_order_id"
    ] == ("client_order_id",)

    decision_columns = _columns(inspector, "execution_order_decisions")
    assert {
        "id",
        "order_intent_id",
        "decision_type",
        "reason_code",
        "message",
        "policy_payload",
        "created_at",
    } <= set(decision_columns)
    decision_indexes = _index_columns(inspector, "execution_order_decisions")
    assert decision_indexes["ix_execution_order_decisions_order_intent_id"] == (
        "order_intent_id",
    )
    assert decision_indexes["ix_execution_order_decisions_decision_type"] == (
        "decision_type",
    )
    assert decision_indexes["ix_execution_order_decisions_reason_code"] == (
        "reason_code",
    )
    assert decision_indexes["ix_execution_order_decisions_created_at"] == ("created_at",)

    approval_columns = _columns(inspector, "operator_approval_requests")
    assert {
        "id",
        "resource_type",
        "resource_id",
        "status",
        "reason_code",
        "requested_by",
        "requested_at",
        "decided_by",
        "decided_at",
        "operator_note",
        "expires_at",
    } <= set(approval_columns)
    approval_indexes = _index_columns(inspector, "operator_approval_requests")
    assert approval_indexes["ix_operator_approval_requests_resource"] == (
        "resource_type",
        "resource_id",
    )
    assert approval_indexes["uq_operator_approval_requests_pending_resource"] == (
        "resource_type",
        "resource_id",
    )
    pending_index = _index_by_name(
        inspector,
        "operator_approval_requests",
        "uq_operator_approval_requests_pending_resource",
    )
    assert pending_index["unique"] == 1
    for name, columns in {
        "ix_operator_approval_requests_resource_type": ("resource_type",),
        "ix_operator_approval_requests_resource_id": ("resource_id",),
        "ix_operator_approval_requests_status": ("status",),
        "ix_operator_approval_requests_reason_code": ("reason_code",),
        "ix_operator_approval_requests_requested_at": ("requested_at",),
        "ix_operator_approval_requests_decided_at": ("decided_at",),
        "ix_operator_approval_requests_expires_at": ("expires_at",),
    }.items():
        assert approval_indexes[name] == columns

    incident_columns = _columns(inspector, "safety_incidents")
    assert {
        "id",
        "severity",
        "category",
        "status",
        "resource_type",
        "resource_id",
        "reason_code",
        "message",
        "payload",
        "created_at",
        "acknowledged_by",
        "acknowledged_at",
        "resolved_by",
        "resolved_at",
    } <= set(incident_columns)
    incident_indexes = _index_columns(inspector, "safety_incidents")
    for name, columns in {
        "ix_safety_incidents_severity": ("severity",),
        "ix_safety_incidents_category": ("category",),
        "ix_safety_incidents_status": ("status",),
        "ix_safety_incidents_resource_type": ("resource_type",),
        "ix_safety_incidents_resource_id": ("resource_id",),
        "ix_safety_incidents_reason_code": ("reason_code",),
        "ix_safety_incidents_created_at": ("created_at",),
    }.items():
        assert incident_indexes[name] == columns

    event_columns = _columns(inspector, "kill_switch_events")
    assert {
        "id",
        "scope",
        "previous_state_payload",
        "new_state_payload",
        "operator",
        "reason",
        "created_at",
    } <= set(event_columns)
    event_indexes = _index_columns(inspector, "kill_switch_events")
    assert event_indexes["ix_kill_switch_events_scope"] == ("scope",)
    assert event_indexes["ix_kill_switch_events_created_at"] == ("created_at",)


def _assert_agent_intelligence_schema(inspector) -> None:
    tables = set(inspector.get_table_names())
    assert {
        "strategy_skills",
        "agent_learning_memories",
        "agent_review_board_runs",
        "agent_review_board_votes",
    } <= tables

    skill_columns = _columns(inspector, "strategy_skills")
    assert {
        "id",
        "skill_key",
        "version",
        "display_name",
        "description",
        "status",
        "template_type",
        "supported_markets_payload",
        "required_data_fields_payload",
        "parameter_schema_payload",
        "validation_rules_payload",
        "risk_notes_payload",
        "prompt_guidance",
        "created_at",
        "updated_at",
    } <= set(skill_columns)
    assert skill_columns["skill_key"]["nullable"] is False
    assert skill_columns["version"]["nullable"] is False
    skill_uniques = _unique_columns(inspector, "strategy_skills")
    assert skill_uniques["uq_strategy_skills_key_version"] == (
        "skill_key",
        "version",
    )

    memory_columns = _columns(inspector, "agent_learning_memories")
    assert {
        "id",
        "memory_type",
        "scope",
        "symbol",
        "strategy_skill_id",
        "source_type",
        "source_id",
        "title",
        "content",
        "reason_code",
        "evidence_payload",
        "confidence",
        "importance",
        "status",
        "expires_at",
        "created_at",
        "created_by",
        "retired_at",
        "retired_by",
        "retired_reason",
    } <= set(memory_columns)
    assert memory_columns["memory_type"]["nullable"] is False
    assert memory_columns["source_id"]["nullable"] is False
    memory_indexes = _index_columns(inspector, "agent_learning_memories")
    assert memory_indexes["uq_agent_learning_memories_active_source_reason"] == (
        "memory_type",
        "source_type",
        "source_id",
        "reason_code",
    )
    active_memory_index = _index_by_name(
        inspector,
        "agent_learning_memories",
        "uq_agent_learning_memories_active_source_reason",
    )
    assert active_memory_index["unique"] == 1
    active_memory_where = _where_text(active_memory_index)
    assert "status" in active_memory_where
    assert "active" in active_memory_where

    board_columns = _columns(inspector, "agent_review_board_runs")
    assert {
        "id",
        "subject_type",
        "subject_id",
        "status",
        "coordinator_agent_run_id",
        "final_recommendation",
        "blocking_reason_codes_payload",
        "memory_ids_payload",
        "summary_payload",
        "created_at",
        "finished_at",
        "duration_ms",
    } <= set(board_columns)

    vote_columns = _columns(inspector, "agent_review_board_votes")
    assert {
        "id",
        "board_run_id",
        "reviewer_role",
        "agent_run_id",
        "vote",
        "reason_code",
        "rationale",
        "evidence_payload",
        "created_at",
    } <= set(vote_columns)


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
    _assert_pre_live_safety_ops_schema(inspector)
    _assert_agent_intelligence_schema(inspector)

    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "select scope, kill_switch_active, dry_run_enabled, "
                "simulated_enabled, live_enabled "
                "from execution_safety_states where scope = 'global'"
            )
        ).one()
        partial_index_sql = connection.execute(
            text(
                "select sql from sqlite_master "
                "where type = 'index' "
                "and name = 'uq_operator_approval_requests_pending_resource'"
            )
        ).scalar_one()
        ma_cross_seed = connection.execute(
            text(
                "select skill_key, version, status, template_type, "
                "supported_markets_payload, required_data_fields_payload, "
                "parameter_schema_payload, validation_rules_payload, "
                "risk_notes_payload, prompt_guidance "
                "from strategy_skills where skill_key = 'ma_cross'"
            )
        ).one()
    assert tuple(row) == ("global", False, True, True, False)
    assert "WHERE status = 'pending'" in partial_index_sql
    assert tuple(ma_cross_seed) == (
        "ma_cross",
        "1.0.0",
        "active",
        "deterministic_template",
        '["A_STOCK"]',
        '["open","high","low","close","volume","timestamp","symbol"]',
        '{"short_window":{"type":"positive_int"},"long_window":{"type":"positive_int_gt_short_window"},"order_size":{"type":"positive_int"},"initial_cash":{"type":"positive_decimal_string"}}',
        '{"no_generated_code":true,"no_live_trading_recommendation":true,"readiness_floor_caps_review":true}',
        '{"template_risks":["trend-following lag","sideways whipsaw","parameter overfit"]}',
        "Use only for deterministic moving-average crossover research. Do not output executable code or trading instructions.",
    )


def test_validation_report_migration_downgrade_and_reupgrade(
    tmp_path: Path, monkeypatch
):
    db_path = tmp_path / "runtime.sqlite3"
    database_url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")
    _assert_validation_report_schema(_inspector(database_url))
    _assert_pre_live_safety_ops_schema(_inspector(database_url))
    _assert_agent_intelligence_schema(_inspector(database_url))

    command.downgrade(config, "20260624_0008")
    downgraded_inspector = _inspector(database_url)
    downgraded_tables = set(downgraded_inspector.get_table_names())
    assert "data_quality_reports" not in downgraded_tables
    assert "research_validation_reports" not in downgraded_tables
    assert "execution_safety_states" not in downgraded_tables
    assert "execution_order_intents" not in downgraded_tables
    assert "execution_order_decisions" not in downgraded_tables
    assert "operator_approval_requests" not in downgraded_tables
    assert "safety_incidents" not in downgraded_tables
    assert "kill_switch_events" not in downgraded_tables
    assert "strategy_skills" not in downgraded_tables
    assert "agent_learning_memories" not in downgraded_tables
    assert "agent_review_board_runs" not in downgraded_tables
    assert "agent_review_board_votes" not in downgraded_tables
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
    _assert_pre_live_safety_ops_schema(reupgraded_inspector)
    _assert_agent_intelligence_schema(reupgraded_inspector)
