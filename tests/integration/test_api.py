from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.core.enums import Market, OrderSide, StrategyStatus
from quant_trading.core.models import OrderIntent
from quant_trading.paper.engine import PaperTradingEngine
from quant_trading.risk.engine import RiskEngine
from quant_trading.risk.rules import (
    MaxOrderValueRule,
    NoTradeWithoutDataRule,
    PriceSanityRule,
    StrategyStatusRule,
)
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import BacktestRunORM, PortfolioSnapshotORM
from quant_trading.storage.repositories import InstrumentRepository


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine)), engine


class ApiBuyIfFlatStrategy:
    name = "api_buy_if_flat"

    def on_bar(self, bars, portfolio):
        latest = bars[-1]
        if latest.instrument_id in portfolio.positions:
            return []
        return [
            OrderIntent(
                instrument_id=latest.instrument_id,
                symbol=latest.symbol,
                side=OrderSide.BUY,
                quantity=100,
                reason="api_read_seed_buy",
            )
        ]


def seed_paper_run(engine, legacy_sqlite_db):
    import_legacy_sqlite(legacy_sqlite_db, engine)
    paper = PaperTradingEngine(
        engine=engine,
        initial_cash=Decimal("100000"),
        risk_engine=RiskEngine(
            [
                StrategyStatusRule(),
                NoTradeWithoutDataRule(),
                PriceSanityRule(),
                MaxOrderValueRule(max_order_value=Decimal("100000")),
            ]
        ),
    )
    strategy = ApiBuyIfFlatStrategy()
    account_id = paper.create_account(
        name="API Paper Account",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )
    run_id = paper.start_run(
        account_id=account_id,
        symbol="000001",
        strategy=strategy,
        strategy_name=strategy.name,
        strategy_status=StrategyStatus.APPROVED,
    )
    paper.run_one_tick(
        run_id=run_id,
        strategy=strategy,
        strategy_status=StrategyStatus.APPROVED,
    )
    return account_id, run_id


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


def test_paper_read_apis_list_persisted_account_run_and_execution_state(legacy_sqlite_db):
    client, engine = make_client()
    account_id, run_id = seed_paper_run(engine, legacy_sqlite_db)

    accounts_response = client.get("/paper/accounts")
    account_response = client.get(f"/paper/accounts/{account_id}")
    runs_response = client.get("/paper/runs")
    run_response = client.get(f"/paper/runs/{run_id}")
    positions_response = client.get(f"/paper/accounts/{account_id}/positions")
    ledger_response = client.get(f"/paper/accounts/{account_id}/cash-ledger")
    orders_response = client.get(f"/paper/runs/{run_id}/orders")
    fills_response = client.get(f"/paper/runs/{run_id}/fills")
    risk_response = client.get(f"/paper/runs/{run_id}/risk-decisions")
    snapshots_response = client.get(f"/paper/runs/{run_id}/snapshots")

    responses = [
        accounts_response,
        account_response,
        runs_response,
        run_response,
        positions_response,
        ledger_response,
        orders_response,
        fills_response,
        risk_response,
        snapshots_response,
    ]
    assert [response.status_code for response in responses] == [200] * len(responses)

    accounts = accounts_response.json()
    assert accounts[0]["id"] == account_id
    assert accounts[0]["name"] == "API Paper Account"
    assert accounts[0]["initial_cash"] == 100000.0
    assert accounts[0]["status"] == "active"
    assert account_response.json() == accounts[0]

    runs = runs_response.json()
    assert runs[0]["id"] == run_id
    assert runs[0]["account_id"] == account_id
    assert runs[0]["strategy_name"] == "api_buy_if_flat"
    assert runs[0]["symbol"] == "000001"
    assert runs[0]["status"] == "running"
    assert runs[0]["last_processed_at"] == "2026-05-01"
    assert run_response.json() == runs[0]

    positions = positions_response.json()
    assert len(positions) == 1
    assert positions[0]["account_id"] == account_id
    assert positions[0]["symbol"] == "000001"
    assert positions[0]["quantity"] == 100
    assert positions[0]["avg_cost"] > 0

    ledger = ledger_response.json()
    assert [row["event_type"] for row in ledger] == [
        "initial_deposit",
        "buy_notional",
        "commission",
    ]
    assert ledger[0]["account_id"] == account_id
    assert ledger[0]["amount"] == 100000.0
    assert ledger[1]["run_id"] == run_id

    orders = orders_response.json()
    assert len(orders) == 1
    assert orders[0]["run_id"] == run_id
    assert orders[0]["account_id"] == account_id
    assert orders[0]["symbol"] == "000001"
    assert orders[0]["side"] == "buy"
    assert orders[0]["quantity"] == 100
    assert orders[0]["status"] == "filled"
    assert orders[0]["risk_decision"] == "approved"

    fills = fills_response.json()
    assert len(fills) == 1
    assert fills[0]["run_id"] == run_id
    assert fills[0]["account_id"] == account_id
    assert fills[0]["order_id"] == orders[0]["id"]
    assert fills[0]["price"] > 0
    assert fills[0]["commission"] > 0

    risk_decisions = risk_response.json()
    assert len(risk_decisions) == 1
    assert risk_decisions[0]["run_id"] == run_id
    assert risk_decisions[0]["order_id"] == orders[0]["id"]
    assert risk_decisions[0]["decision"] == "approved"

    snapshots = snapshots_response.json()
    assert len(snapshots) == 1
    assert snapshots[0]["account_id"] == account_id
    assert snapshots[0]["timestamp"] == "2026-05-01"
    assert snapshots[0]["cash"] == ledger[-1]["cash_after"]
    assert snapshots[0]["market_value"] > 0
