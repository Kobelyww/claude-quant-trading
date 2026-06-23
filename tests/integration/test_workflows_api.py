import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from quant_trading.api.main import create_app
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import CashLedgerORM, PaperRunORM


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine)), engine


def test_workflow_command_api_runs_import_backtest_paper_tick(legacy_sqlite_db: Path):
    client, engine = make_client()

    import_response = client.post(
        "/workflows/import-legacy",
        json={"legacy_db_path": str(legacy_sqlite_db)},
    )
    backtest_response = client.post(
        "/workflows/backtests/ma-cross",
        json={
            "symbol": "000001",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
            "initial_cash": "100000",
        },
    )
    account_response = client.post(
        "/workflows/paper/accounts",
        json={"name": "API Workflow Account", "initial_cash": "100000"},
    )
    assert account_response.status_code == 200
    account_payload = account_response.json()
    run_response = client.post(
        "/workflows/paper/runs/ma-cross",
        json={
            "account_id": account_payload["account_id"],
            "symbol": "000001",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
        },
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    tick_response = client.post(f"/workflows/paper/runs/{run_payload['run_id']}/tick")

    assert import_response.status_code == 200
    assert import_response.json() == {"imported_symbols": 1, "imported_bars": 121}

    assert backtest_response.status_code == 200
    backtest_payload = backtest_response.json()
    assert backtest_payload["run_id"] > 0
    assert backtest_payload["symbol"] == "000001"
    assert backtest_payload["strategy_name"] == "ma_cross"
    assert float(backtest_payload["final_equity"]) > 0
    assert backtest_payload["equity_points"] == 121

    assert account_payload["account_id"] > 0
    assert account_payload["name"] == "API Workflow Account"
    assert account_payload["initial_cash"] == "100000"
    assert account_payload["base_currency"] == "CNY"

    assert run_payload["run_id"] > 0
    assert run_payload["account_id"] == account_payload["account_id"]
    assert run_payload["symbol"] == "000001"
    assert run_payload["strategy_name"] == "ma_cross"
    assert run_payload["status"] == "running"

    assert tick_response.status_code == 200
    tick_payload = tick_response.json()
    assert tick_payload["run_id"] == run_payload["run_id"]
    assert tick_payload["account_id"] == account_payload["account_id"]
    assert tick_payload["snapshot_created"] is True
    assert tick_payload["idempotent_noop"] is False

    with session_scope(engine) as session:
        paper_run = session.get(PaperRunORM, run_payload["run_id"])
        ledger_rows = session.scalars(
            select(CashLedgerORM).where(CashLedgerORM.account_id == account_payload["account_id"])
        ).all()

    assert paper_run.strategy_config
    assert json.loads(paper_run.strategy_config)["strategy_name"] == "ma_cross"
    assert ledger_rows


def test_workflow_command_api_validates_invalid_payloads(legacy_sqlite_db: Path):
    client, _ = make_client()
    import_response = client.post(
        "/workflows/import-legacy",
        json={"legacy_db_path": str(legacy_sqlite_db)},
    )

    invalid_backtest_response = client.post(
        "/workflows/backtests/ma-cross",
        json={
            "symbol": "000001",
            "short_window": 8,
            "long_window": 8,
            "order_size": 50,
            "initial_cash": "100000",
        },
    )
    blank_account_response = client.post(
        "/workflows/paper/accounts",
        json={"name": "   ", "initial_cash": "100000"},
    )
    missing_tick_response = client.post("/workflows/paper/runs/999999/tick")

    assert import_response.status_code == 200
    assert invalid_backtest_response.status_code in {400, 422}
    assert blank_account_response.status_code in {400, 422}
    assert missing_tick_response.status_code == 404


def test_workflow_command_api_rejects_backtest_symbol_without_market_bars(
    legacy_sqlite_db: Path,
):
    client, _ = make_client()
    import_response = client.post(
        "/workflows/import-legacy",
        json={"legacy_db_path": str(legacy_sqlite_db)},
    )

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

    assert import_response.status_code == 200
    assert response.status_code == 400
    assert "no market bars found" in response.json()["detail"]


def test_workflow_command_api_maps_missing_legacy_import_path_to_404(tmp_path: Path):
    client, _ = make_client()
    missing_path = tmp_path / "missing.sqlite3"

    response = client.post(
        "/workflows/import-legacy",
        json={"legacy_db_path": str(missing_path)},
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert str(missing_path) in detail or "not found" in detail.lower()


def test_workflow_run_read_api_lists_and_gets_runs(legacy_sqlite_db: Path):
    client, _ = make_client()
    client.post("/workflows/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    list_response = client.get("/workflows/runs")

    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) == 1
    assert rows[0]["command_name"] == "import_legacy"
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["error_message"] is None
    assert rows[0]["result_payload"]["imported_bars"] == 121

    detail_response = client.get(f"/workflows/runs/{rows[0]['id']}")

    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == rows[0]["id"]


def test_workflow_run_read_api_filters_by_status_and_command(legacy_sqlite_db: Path):
    client, _ = make_client()
    client.post("/workflows/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})
    client.post(
        "/workflows/backtests/ma-cross",
        json={
            "symbol": "NO_SUCH",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
            "initial_cash": "100000",
        },
    )

    response = client.get(
        "/workflows/runs",
        params={"status": "failed", "command_name": "backtest_ma_cross"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["command_name"] == "backtest_ma_cross"


def test_workflow_run_read_api_returns_404_for_missing_run():
    client, _ = make_client()

    response = client.get("/workflows/runs/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "workflow run not found"
