import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import WorkflowRunORM
from quant_trading.workflows.runner import (
    WorkflowCommandRunner,
    record_failed_workflow_command,
    workflow_payload_dumps,
)


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def workflow_runs(engine):
    with session_scope(engine) as session:
        return list(session.scalars(select(WorkflowRunORM).order_by(WorkflowRunORM.id)).all())


def test_runner_records_successful_command():
    engine = make_engine_with_schema()

    result = WorkflowCommandRunner(engine).run(
        "paper_create_account",
        {"name": "Audit Paper", "initial_cash": Decimal("100000")},
        lambda: {"account_id": 7, "name": "Audit Paper"},
    )

    assert result == {"account_id": 7, "name": "Audit Paper"}
    runs = workflow_runs(engine)
    assert len(runs) == 1
    run = runs[0]
    assert run.command_name == "paper_create_account"
    assert run.status == "succeeded"
    assert run.created_object_type == "paper_account"
    assert run.created_object_id == 7
    assert json.loads(run.request_payload)["initial_cash"] == "100000"
    assert json.loads(run.result_payload)["account_id"] == 7
    assert run.finished_at is not None
    assert run.duration_ms is not None


def test_runner_can_return_workflow_run_id_with_result():
    engine = make_engine_with_schema()

    execution = WorkflowCommandRunner(engine).run_with_audit(
        "paper_create_account",
        {"name": "Audit Paper"},
        lambda: {"account_id": 9},
    )

    assert execution.result == {"account_id": 9}
    assert execution.workflow_run_id == 1


def test_runner_records_failed_command_and_reraises():
    engine = make_engine_with_schema()

    with pytest.raises(ValueError, match="no market bars found"):
        WorkflowCommandRunner(engine).run(
            "backtest_ma_cross",
            {"symbol": "NO_SUCH"},
            lambda: (_raise_value_error("no market bars found for symbol: NO_SUCH")),
        )

    run = workflow_runs(engine)[0]
    assert run.command_name == "backtest_ma_cross"
    assert run.status == "failed"
    assert "no market bars found" in run.error_message
    assert json.loads(run.result_payload) == {}


def test_record_failed_workflow_command_does_not_raise():
    engine = make_engine_with_schema()

    record_failed_workflow_command(
        engine,
        "paper_create_account",
        {"validation_error_count": 1},
        "request validation failed",
    )

    run = workflow_runs(engine)[0]
    assert run.command_name == "paper_create_account"
    assert run.status == "failed"
    assert run.error_message == "request validation failed"


def test_runner_serializes_decimal_values_as_strings():
    payload = json.loads(workflow_payload_dumps({"cash": Decimal("100000.00")}))

    assert payload == {"cash": "100000"}


def _raise_value_error(message: str):
    raise ValueError(message)
