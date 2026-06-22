from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.core.enums import Market
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import BacktestRunORM, PortfolioSnapshotORM
from quant_trading.storage.repositories import InstrumentRepository


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine)), engine


def test_health_endpoint_returns_ok():
    client, _ = make_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_instruments_endpoint_lists_normalized_instruments():
    client, engine = make_client()
    with session_scope(engine) as session:
        InstrumentRepository(session).upsert_symbol(
            symbol="000001",
            name="Ping An Bank",
            market=Market.A_STOCK,
            asset_type="stock",
            currency="CNY",
            exchange="SZSE",
        )

    response = client.get("/instruments")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "symbol": "000001",
            "name": "Ping An Bank",
            "market": "a_stock",
            "asset_type": "stock",
            "currency": "CNY",
            "exchange": "SZSE",
            "status": "active",
        }
    ]


def test_backtests_endpoint_lists_persisted_runs():
    client, engine = make_client()
    with session_scope(engine) as session:
        session.add(
            BacktestRunORM(
                strategy_name="ma_cross",
                symbol="000001",
                initial_cash=Decimal("100000"),
                final_equity=Decimal("101234.56"),
                status="done",
            )
        )

    response = client.get("/backtests")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "symbol": "000001",
            "strategy_name": "ma_cross",
            "initial_cash": 100000.0,
            "final_equity": 101234.56,
            "status": "done",
        }
    ]


def test_paper_snapshots_endpoint_lists_latest_snapshots_first():
    client, engine = make_client()
    with session_scope(engine) as session:
        session.add_all(
            [
                PortfolioSnapshotORM(
                    account_id=1,
                    timestamp=date(2026, 1, 1),
                    equity=Decimal("100000"),
                    cash=Decimal("100000"),
                    market_value=Decimal("0"),
                    realized_pnl=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                    drawdown=Decimal("0"),
                ),
                PortfolioSnapshotORM(
                    account_id=1,
                    timestamp=date(2026, 1, 2),
                    equity=Decimal("100500"),
                    cash=Decimal("99000"),
                    market_value=Decimal("1500"),
                    realized_pnl=Decimal("0"),
                    unrealized_pnl=Decimal("500"),
                    drawdown=Decimal("0"),
                ),
            ]
        )

    response = client.get("/paper/snapshots")

    assert response.status_code == 200
    payload = response.json()
    assert [row["timestamp"] for row in payload] == ["2026-01-02", "2026-01-01"]
    assert payload[0]["equity"] == 100500.0
    assert payload[0]["market_value"] == 1500.0
