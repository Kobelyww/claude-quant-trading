from pathlib import Path

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.storage.db import create_all, make_engine


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine))


def test_operator_can_complete_core_workflow_over_http(legacy_sqlite_db: Path):
    client = make_client()

    import_response = client.post(
        "/workflows/import-legacy",
        json={"legacy_db_path": str(legacy_sqlite_db)},
    )
    assert import_response.status_code == 200

    backtest_response = client.post(
        "/workflows/backtests/ma-cross",
        json={
            "symbol": "000001",
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
            "initial_cash": 100000,
        },
    )
    assert backtest_response.status_code == 200

    account_response = client.post(
        "/workflows/paper/accounts",
        json={
            "name": "E2E Paper",
            "initial_cash": 100000,
            "base_currency": "CNY",
        },
    )
    assert account_response.status_code == 200
    account_id = account_response.json()["account_id"]

    run_response = client.post(
        "/workflows/paper/runs/ma-cross",
        json={
            "account_id": account_id,
            "symbol": "000001",
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
            "max_order_value": 100000,
        },
    )
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    tick_response = client.post(f"/workflows/paper/runs/{run_id}/tick")
    assert tick_response.status_code == 200
    assert tick_response.json()["idempotent_noop"] is False

    idempotent_tick_response = client.post(f"/workflows/paper/runs/{run_id}/tick")
    assert idempotent_tick_response.status_code == 200
    assert idempotent_tick_response.json()["idempotent_noop"] is True

    read_responses = {
        "instruments": client.get("/instruments"),
        "backtests": client.get("/backtests"),
        "accounts": client.get("/paper/accounts"),
        "account_detail": client.get(f"/paper/accounts/{account_id}"),
        "positions": client.get(f"/paper/accounts/{account_id}/positions"),
        "cash_ledger": client.get(f"/paper/accounts/{account_id}/cash-ledger"),
        "runs": client.get("/paper/runs"),
        "run_detail": client.get(f"/paper/runs/{run_id}"),
        "orders": client.get(f"/paper/runs/{run_id}/orders"),
        "fills": client.get(f"/paper/runs/{run_id}/fills"),
        "risk_decisions": client.get(f"/paper/runs/{run_id}/risk-decisions"),
        "snapshots": client.get(f"/paper/runs/{run_id}/snapshots"),
        "dashboard": client.get("/dashboard"),
    }
    assert {
        name: response.status_code for name, response in read_responses.items()
    } == {name: 200 for name in read_responses}

    instruments = read_responses["instruments"].json()
    assert instruments[0]["symbol"] == "000001"

    backtests = read_responses["backtests"].json()
    assert backtests[0]["strategy_name"] == "ma_cross"

    account_detail = read_responses["account_detail"].json()
    assert account_detail["name"] == "E2E Paper"

    dashboard_html = read_responses["dashboard"].text
    assert dashboard_html.count("Operations Workbench") == 1
