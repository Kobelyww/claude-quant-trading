from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from quant_trading.api.main import create_app
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import PaperAccountORM, PaperRunORM


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine)), engine


def test_dashboard_renders_workflow_forms_and_empty_state():
    client, _ = make_client()

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Operations Workbench" in html
    assert 'action="/dashboard/actions/import-legacy"' in html
    assert 'action="/dashboard/actions/backtests/ma-cross"' in html
    assert 'action="/dashboard/actions/paper/accounts"' in html
    assert 'action="/dashboard/actions/paper/runs/ma-cross"' in html
    assert 'action="/dashboard/actions/paper/tick"' in html
    assert "Backtest Runs" in html
    assert "Paper Accounts" in html


def test_dashboard_displays_seeded_workflow_state(legacy_sqlite_db: Path):
    client, _ = make_client()
    client.post(
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
        json={"name": "Dashboard Paper", "initial_cash": "100000"},
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
    client.post(f"/workflows/paper/runs/{run_response.json()['run_id']}/tick")

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "000001" in html
    assert "Dashboard Paper" in html
    assert f"#{backtest_response.json()['run_id']}" in html
    assert f"#{run_response.json()['run_id']}" in html
    assert "running" in html


def test_dashboard_form_actions_complete_core_workflow(legacy_sqlite_db: Path):
    client, engine = make_client()

    import_response = client.post(
        "/dashboard/actions/import-legacy",
        data={"legacy_db_path": str(legacy_sqlite_db)},
        follow_redirects=False,
    )
    backtest_response = client.post(
        "/dashboard/actions/backtests/ma-cross",
        data={
            "symbol": "000001",
            "short_window": "3",
            "long_window": "8",
            "order_size": "50",
            "initial_cash": "100000",
        },
        follow_redirects=False,
    )
    account_response = client.post(
        "/dashboard/actions/paper/accounts",
        data={"name": "Form Paper", "initial_cash": "100000"},
        follow_redirects=False,
    )
    with session_scope(engine) as session:
        account_id = session.scalar(
            select(PaperAccountORM.id).where(PaperAccountORM.name == "Form Paper")
        )
    run_response = client.post(
        "/dashboard/actions/paper/runs/ma-cross",
        data={
            "account_id": str(account_id),
            "symbol": "000001",
            "short_window": "3",
            "long_window": "8",
            "order_size": "50",
            "max_order_value": "100000",
        },
        follow_redirects=False,
    )
    with session_scope(engine) as session:
        run_id = session.scalar(
            select(PaperRunORM.id).where(PaperRunORM.account_id == account_id)
        )
    tick_response = client.post(
        "/dashboard/actions/paper/tick",
        data={"run_id": str(run_id)},
        follow_redirects=False,
    )

    assert import_response.status_code == 303
    assert backtest_response.status_code == 303
    assert account_response.status_code == 303
    assert run_response.status_code == 303
    assert tick_response.status_code == 303

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Form Paper" in html
    assert "000001" in html
    assert "Paper Runs" in html
    assert "Snapshots" in html
    assert f"#{run_id}" in html


def test_dashboard_account_form_error_displays_plain_message():
    client, _ = make_client()

    response = client.post(
        "/dashboard/actions/paper/accounts",
        data={"name": "   ", "initial_cash": "100000"},
    )

    assert response.status_code == 400
    assert "name is required" in response.text


def test_dashboard_backtest_action_rejects_symbol_without_market_bars(
    legacy_sqlite_db: Path,
):
    client, _ = make_client()
    import_response = client.post(
        "/workflows/import-legacy",
        json={"legacy_db_path": str(legacy_sqlite_db)},
    )

    response = client.post(
        "/dashboard/actions/backtests/ma-cross",
        data={
            "symbol": "NO_SUCH",
            "short_window": "3",
            "long_window": "8",
            "order_size": "50",
            "initial_cash": "100000",
        },
    )

    assert import_response.status_code == 200
    assert response.status_code == 400
    assert "no market bars found" in response.text
