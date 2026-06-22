from decimal import Decimal

from sqlalchemy import select

from quant_trading.core.enums import PaperRunStatus, StrategyStatus
from quant_trading.paper.engine import PaperTradingEngine
from quant_trading.risk.engine import RiskEngine
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import CashLedgerORM, PaperAccountORM, PaperRunORM


class NoopStrategy:
    name = "noop"

    def on_bar(self, bars, portfolio):
        return []


def make_paper_engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return PaperTradingEngine(
        engine=engine,
        initial_cash=Decimal("100000"),
        risk_engine=RiskEngine([]),
    ), engine


def test_create_account_persists_initial_cash_ledger_once():
    paper, engine = make_paper_engine()

    account_id = paper.create_account(
        name="Stage 2 Paper",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )

    duplicate_account_id = paper.create_account(
        name="Stage 2 Paper",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )

    with session_scope(engine) as session:
        account = session.get(PaperAccountORM, account_id)
        ledger_rows = session.scalars(
            select(CashLedgerORM).where(CashLedgerORM.account_id == account_id)
        ).all()

    assert duplicate_account_id != account_id
    assert account.name == "Stage 2 Paper"
    assert account.initial_cash == Decimal("100000.000000")
    assert len(ledger_rows) == 1
    assert ledger_rows[0].event_type == "initial_deposit"
    assert ledger_rows[0].amount == Decimal("100000.000000")
    assert ledger_rows[0].cash_after == Decimal("100000.000000")


def test_start_run_links_account_strategy_symbol_and_status():
    paper, engine = make_paper_engine()
    account_id = paper.create_account(
        name="Stage 2 Paper",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )

    run_id = paper.start_run(
        account_id=account_id,
        symbol="000001",
        strategy=NoopStrategy(),
        strategy_name="noop",
        strategy_status=StrategyStatus.APPROVED,
        risk_config={"max_order_value": "100000"},
    )

    with session_scope(engine) as session:
        run = session.get(PaperRunORM, run_id)

    assert run.account_id == account_id
    assert run.strategy_name == "noop"
    assert run.symbol == "000001"
    assert run.status == PaperRunStatus.RUNNING.value
    assert run.universe_config == '{"symbols":["000001"]}'
    assert run.strategy_config == '{"strategy_name":"noop"}'
    assert run.risk_config == '{"max_order_value":"100000"}'
