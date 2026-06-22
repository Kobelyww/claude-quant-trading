from datetime import date
from decimal import Decimal

from sqlalchemy import select

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    CashLedgerORM,
    PaperAccountORM,
    PaperFillORM,
    PaperOrderORM,
    PaperPositionORM,
    PaperRunORM,
)


def test_paper_persistence_tables_round_trip():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    with session_scope(engine) as session:
        account = PaperAccountORM(
            name="Stage 2 Account",
            base_currency="CNY",
            initial_cash=Decimal("100000"),
            status="active",
        )
        session.add(account)
        session.flush()
        run = PaperRunORM(
            account_id=account.id,
            strategy_name="one_shot_buy",
            symbol="000001",
            universe_config='{"symbols":["000001"]}',
            strategy_config='{"order_size":100}',
            risk_config='{"max_order_value":"100000"}',
            status="running",
        )
        session.add(run)
        session.flush()
        order = PaperOrderORM(
            run_id=run.id,
            account_id=account.id,
            instrument_id=1,
            symbol="000001",
            side="buy",
            order_type="market",
            quantity=100,
            reason="paper_tick_entry",
            status="filled",
            risk_decision="approved",
            submitted_at=date(2026, 1, 2),
        )
        session.add(order)
        session.flush()
        fill = PaperFillORM(
            run_id=run.id,
            account_id=account.id,
            order_id=order.id,
            instrument_id=1,
            symbol="000001",
            side="buy",
            quantity=100,
            price=Decimal("10.20"),
            commission=Decimal("0.31"),
            slippage=Decimal("1.02"),
            filled_at=date(2026, 1, 2),
        )
        session.add(fill)
        session.flush()
        session.add(
            PaperPositionORM(
                account_id=account.id,
                instrument_id=1,
                symbol="000001",
                quantity=100,
                avg_cost=Decimal("10.2031"),
                market_price=Decimal("10.20"),
                realized_pnl=Decimal("0"),
                updated_at=date(2026, 1, 2),
            )
        )
        session.add(
            CashLedgerORM(
                account_id=account.id,
                run_id=run.id,
                order_id=order.id,
                fill_id=fill.id,
                event_type="buy_notional",
                amount=Decimal("-1020"),
                cash_after=Decimal("98980"),
                currency="CNY",
                occurred_at=date(2026, 1, 2),
            )
        )

    with session_scope(engine) as session:
        loaded_run = session.scalar(select(PaperRunORM).where(PaperRunORM.symbol == "000001"))
        loaded_order = session.scalar(select(PaperOrderORM).where(PaperOrderORM.run_id == loaded_run.id))
        loaded_fill = session.scalar(select(PaperFillORM).where(PaperFillORM.order_id == loaded_order.id))
        loaded_position = session.scalar(select(PaperPositionORM).where(PaperPositionORM.account_id == loaded_run.account_id))
        loaded_ledger = session.scalar(select(CashLedgerORM).where(CashLedgerORM.fill_id == loaded_fill.id))

    assert loaded_run.status == "running"
    assert loaded_order.status == "filled"
    assert loaded_fill.price == Decimal("10.200000")
    assert loaded_position.quantity == 100
    assert loaded_ledger.cash_after == Decimal("98980.000000")
