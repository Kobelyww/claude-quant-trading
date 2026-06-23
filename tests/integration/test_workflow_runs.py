import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import WorkflowRunORM


def make_client(require_auth: bool = False):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    settings = AppSettings(require_auth=require_auth, api_token="local-token")
    return TestClient(create_app(engine=engine, settings=settings)), engine


def workflow_runs(engine):
    with session_scope(engine) as session:
        return list(session.scalars(select(WorkflowRunORM).order_by(WorkflowRunORM.id)).all())


def test_successful_import_creates_succeeded_workflow_run(legacy_sqlite_db: Path):
    client, engine = make_client()

    response = client.post("/workflows/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    assert response.status_code == 200
    runs = workflow_runs(engine)
    assert len(runs) == 1
    run = runs[0]
    assert run.command_name == "import_legacy"
    assert run.status == "succeeded"
    assert run.error_message is None
    assert json.loads(run.request_payload)["legacy_db_path"] == str(legacy_sqlite_db)
    assert json.loads(run.result_payload) == {"imported_symbols": 1, "imported_bars": 121}
    assert run.finished_at is not None
    assert run.duration_ms is not None


def test_backtest_workflow_run_references_backtest_run(legacy_sqlite_db: Path):
    client, engine = make_client()
    client.post("/workflows/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    response = client.post(
        "/workflows/backtests/ma-cross",
        json={
            "symbol": "000001",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
            "initial_cash": "100000",
        },
    )

    assert response.status_code == 200
    run = workflow_runs(engine)[-1]
    assert run.command_name == "backtest_ma_cross"
    assert run.status == "succeeded"
    assert run.created_object_type == "backtest_run"
    assert run.created_object_id == response.json()["run_id"]


def test_paper_commands_record_created_objects(legacy_sqlite_db: Path):
    client, engine = make_client()
    client.post("/workflows/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})
    account_response = client.post(
        "/workflows/paper/accounts",
        json={"name": "Audit Paper", "initial_cash": "100000"},
    )
    run_response = client.post(
        "/workflows/paper/runs/ma-cross",
        json={
            "account_id": account_response.json()["account_id"],
            "symbol": "000001",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
        },
    )
    tick_response = client.post(f"/workflows/paper/runs/{run_response.json()['run_id']}/tick")

    assert account_response.status_code == 200
    assert run_response.status_code == 200
    assert tick_response.status_code == 200
    by_command = {run.command_name: run for run in workflow_runs(engine)}
    assert by_command["paper_create_account"].created_object_type == "paper_account"
    assert by_command["paper_create_account"].created_object_id == account_response.json()["account_id"]
    assert by_command["paper_start_ma_cross_run"].created_object_type == "paper_run"
    assert by_command["paper_start_ma_cross_run"].created_object_id == run_response.json()["run_id"]
    assert by_command["paper_run_tick"].created_object_type == "paper_run"
    assert by_command["paper_run_tick"].created_object_id == tick_response.json()["run_id"]


def test_failed_unknown_symbol_backtest_creates_failed_workflow_run(legacy_sqlite_db: Path):
    client, engine = make_client()
    client.post("/workflows/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    response = client.post(
        "/workflows/backtests/ma-cross",
        json={
            "symbol": "NO_SUCH",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
            "initial_cash": "100000",
        },
    )

    assert response.status_code == 400
    run = workflow_runs(engine)[-1]
    assert run.command_name == "backtest_ma_cross"
    assert run.status == "failed"
    assert "no market bars found" in run.error_message
    assert json.loads(run.result_payload) == {}


def test_validation_failure_creates_failed_workflow_run_for_authorized_command():
    client, engine = make_client()

    response = client.post(
        "/workflows/paper/accounts",
        json={"name": "   ", "initial_cash": "100000"},
    )

    assert response.status_code in {400, 422}
    run = workflow_runs(engine)[0]
    assert run.command_name == "paper_create_account"
    assert run.status == "failed"
    assert run.error_message == "request validation failed"


def test_auth_failure_does_not_create_workflow_run():
    client, engine = make_client(require_auth=True)

    response = client.post(
        "/workflows/paper/accounts",
        json={"name": "Audit Paper", "initial_cash": "100000"},
    )

    assert response.status_code == 401
    assert workflow_runs(engine) == []
