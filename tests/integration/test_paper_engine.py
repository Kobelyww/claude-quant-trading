from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from quant_trading.core.enums import OrderSide, StrategyStatus
from quant_trading.core.models import OrderIntent
from quant_trading.paper.engine import PaperTradingEngine
from quant_trading.paper.repositories import PaperStateRepository
from quant_trading.risk.engine import RiskEngine
from quant_trading.risk.rules import MaxOrderValueRule, NoTradeWithoutDataRule, PriceSanityRule, StrategyStatusRule
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import (
    CashLedgerORM,
    MarketBarORM,
    PaperFillORM,
    PaperOrderORM,
    PaperPositionORM,
    PaperRunORM,
    PortfolioSnapshotORM,
    RiskDecisionORM,
)
from quant_trading.storage.repositories import BrokerOrderEventRepository


@dataclass
class RecordingBuyStrategy:
    name: str = "recording_buy"
    observed: list[tuple[date, Decimal, int]] = field(default_factory=list)

    def on_bar(self, bars, portfolio):
        latest = bars[-1]
        position = portfolio.positions.get(latest.instrument_id)
        self.observed.append(
            (
                latest.timestamp,
                portfolio.cash,
                position.quantity if position else 0,
            )
        )
        if position:
            return []
        return [
            OrderIntent(
                instrument_id=latest.instrument_id,
                symbol=latest.symbol,
                side=OrderSide.BUY,
                quantity=100,
                reason="paper_tick_entry",
            )
        ]


@dataclass
class OversizedBuyStrategy:
    name: str = "oversized_buy"

    def on_bar(self, bars, portfolio):
        latest = bars[-1]
        return [
            OrderIntent(
                instrument_id=latest.instrument_id,
                symbol=latest.symbol,
                side=OrderSide.BUY,
                quantity=100,
                reason="paper_tick_insufficient_cash",
            )
        ]


@dataclass
class SellAllStrategy:
    name: str = "sell_all"

    def on_bar(self, bars, portfolio):
        latest = bars[-1]
        position = portfolio.positions.get(latest.instrument_id)
        if position is None:
            return []
        return [
            OrderIntent(
                instrument_id=latest.instrument_id,
                symbol=latest.symbol,
                side=OrderSide.SELL,
                quantity=position.quantity,
                reason="paper_tick_exit",
            )
        ]


def make_paper_engine(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)
    return (
        PaperTradingEngine(
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
        ),
        engine,
    )


def latest_bar_values(engine):
    with session_scope(engine) as session:
        latest = session.scalar(select(MarketBarORM).order_by(MarketBarORM.timestamp.desc()))
        return (
            latest.instrument_id,
            latest.timestamp,
            latest.open,
            latest.high,
            latest.low,
            latest.close,
            latest.volume,
            latest.adjusted,
            latest.source,
    )


def add_later_bar(engine) -> Decimal:
    (
        instrument_id,
        timestamp,
        open_price,
        high,
        low,
        close,
        volume,
        adjusted,
        source,
    ) = latest_bar_values(engine)
    later_close = close + Decimal("1")
    with session_scope(engine) as session:
        session.add(
            MarketBarORM(
                instrument_id=instrument_id,
                timestamp=timestamp + date.resolution,
                timeframe="1d",
                open=open_price + Decimal("1"),
                high=high + Decimal("1"),
                low=low + Decimal("1"),
                close=later_close,
                volume=volume + Decimal("1"),
                adjusted=adjusted,
                source=source,
            )
        )
    return later_close


def persisted_counts(engine, account_id: int, run_id: int) -> dict[str, int]:
    with session_scope(engine) as session:
        return {
            "orders": session.scalar(
                select(func.count()).select_from(PaperOrderORM).where(PaperOrderORM.run_id == run_id)
            ),
            "fills": session.scalar(
                select(func.count()).select_from(PaperFillORM).where(PaperFillORM.run_id == run_id)
            ),
            "positions": session.scalar(
                select(func.count())
                .select_from(PaperPositionORM)
                .where(PaperPositionORM.account_id == account_id)
            ),
            "ledger": session.scalar(
                select(func.count())
                .select_from(CashLedgerORM)
                .where(CashLedgerORM.account_id == account_id)
            ),
            "snapshots": session.scalar(
                select(func.count())
                .select_from(PortfolioSnapshotORM)
                .where(PortfolioSnapshotORM.account_id == account_id)
            ),
            "risk_decisions": session.scalar(
                select(func.count())
                .select_from(RiskDecisionORM)
                .where(RiskDecisionORM.run_id == run_id)
            ),
        }


def test_paper_tick_persists_approved_buy_and_is_idempotent(legacy_sqlite_db: Path):
    paper, engine = make_paper_engine(legacy_sqlite_db)
    strategy = RecordingBuyStrategy()
    account_id = paper.create_account(
        name="Task 3 Paper",
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

    first = paper.run_one_tick(
        run_id=run_id,
        strategy=strategy,
        strategy_status=StrategyStatus.APPROVED,
    )

    with session_scope(engine) as session:
        run = session.get(PaperRunORM, run_id)
        order = session.scalar(select(PaperOrderORM).where(PaperOrderORM.run_id == run_id))
        fill = session.scalar(select(PaperFillORM).where(PaperFillORM.run_id == run_id))
        position = session.scalar(
            select(PaperPositionORM).where(PaperPositionORM.account_id == account_id)
        )
        ledger_rows = session.scalars(
            select(CashLedgerORM)
            .where(CashLedgerORM.account_id == account_id)
            .order_by(CashLedgerORM.id)
        ).all()
        snapshot = session.scalar(
            select(PortfolioSnapshotORM).where(PortfolioSnapshotORM.account_id == account_id)
        )
        risk_decision = session.scalar(select(RiskDecisionORM).where(RiskDecisionORM.run_id == run_id))
        broker_events = BrokerOrderEventRepository(session).list_for_run(run_id)

    assert first.run_id == run_id
    assert first.account_id == account_id
    assert first.processed_at == run.last_processed_at
    assert first.orders_created == 1
    assert first.orders_filled == 1
    assert first.orders_rejected == 0
    assert first.fills_created == 1
    assert first.snapshot_created is True
    assert first.risk_decision_count == 1
    assert first.idempotent_noop is False
    assert order.status == "filled"
    assert order.risk_decision == "approved"
    assert fill.order_id == order.id
    assert position.quantity == 100
    assert position.symbol == "000001"
    assert len(ledger_rows) == 3
    assert ledger_rows[0].event_type == "initial_deposit"
    assert ledger_rows[1].event_type == "buy_notional"
    assert ledger_rows[1].amount == -fill.price * Decimal(fill.quantity)
    assert ledger_rows[2].event_type == "commission"
    assert ledger_rows[2].amount == -fill.commission
    assert snapshot.cash == ledger_rows[-1].cash_after
    assert snapshot.market_value > Decimal("0")
    assert risk_decision.order_id == order.id
    assert risk_decision.decision == "approved"
    assert len(broker_events) == 1
    assert broker_events[0].broker_mode == "simulated"
    assert broker_events[0].status == "filled"
    assert broker_events[0].accepted is True
    assert json.loads(broker_events[0].result_payload)["has_fill"] is True

    counts_after_first = persisted_counts(engine, account_id, run_id)
    second = paper.run_one_tick(
        run_id=run_id,
        strategy=strategy,
        strategy_status=StrategyStatus.APPROVED,
    )

    assert second.run_id == run_id
    assert second.account_id == account_id
    assert second.processed_at == first.processed_at
    assert second.orders_created == 0
    assert second.orders_filled == 0
    assert second.orders_rejected == 0
    assert second.fills_created == 0
    assert second.snapshot_created is False
    assert second.risk_decision_count == 0
    assert second.idempotent_noop is True
    assert persisted_counts(engine, account_id, run_id) == counts_after_first

    later_close = add_later_bar(engine)
    third = paper.run_one_tick(
        run_id=run_id,
        strategy=strategy,
        strategy_status=StrategyStatus.APPROVED,
    )

    with session_scope(engine) as session:
        marked_position = session.scalar(
            select(PaperPositionORM).where(PaperPositionORM.account_id == account_id)
        )
        latest_snapshot = session.scalar(
            select(PortfolioSnapshotORM)
            .where(PortfolioSnapshotORM.account_id == account_id)
            .order_by(PortfolioSnapshotORM.timestamp.desc())
        )

    assert third.processed_at > first.processed_at
    assert strategy.observed[-1][1] == ledger_rows[-1].cash_after
    assert strategy.observed[-1][2] == 100
    assert third.orders_created == 0
    assert third.fills_created == 0
    assert third.snapshot_created is True
    assert marked_position.market_price == later_close
    assert latest_snapshot.market_value == later_close * Decimal("100")


def test_run_one_tick_rejects_strategy_name_mismatch(legacy_sqlite_db: Path):
    paper, engine = make_paper_engine(legacy_sqlite_db)
    account_id = paper.create_account(
        name="Task 3 Paper",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )
    run_id = paper.start_run(
        account_id=account_id,
        symbol="000001",
        strategy=RecordingBuyStrategy(name="recording_buy"),
        strategy_name="recording_buy",
        strategy_status=StrategyStatus.APPROVED,
    )

    with pytest.raises(ValueError, match="strategy_name must match strategy.name"):
        paper.run_one_tick(
            run_id=run_id,
            strategy=RecordingBuyStrategy(name="other_strategy"),
            strategy_status=StrategyStatus.APPROVED,
        )

    with session_scope(engine) as session:
        run = session.get(PaperRunORM, run_id)
        order_count = session.scalar(
            select(func.count()).select_from(PaperOrderORM).where(PaperOrderORM.run_id == run_id)
        )
        snapshot_count = session.scalar(
            select(func.count())
            .select_from(PortfolioSnapshotORM)
            .where(PortfolioSnapshotORM.account_id == account_id)
        )

    assert run.last_processed_at is None
    assert order_count == 0
    assert snapshot_count == 0


def test_load_run_query_uses_row_lock_for_tick_idempotency():
    sql = str(
        PaperStateRepository.load_run_statement(1).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "FOR UPDATE" in sql


def test_load_account_query_uses_row_lock_for_account_state_serialization():
    sql = str(
        PaperStateRepository.load_account_statement(1).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "FOR UPDATE" in sql


def test_rejected_strategy_status_creates_order_and_risk_decision_without_fill(
    legacy_sqlite_db: Path,
):
    paper, engine = make_paper_engine(legacy_sqlite_db)
    strategy = RecordingBuyStrategy()
    account_id = paper.create_account(
        name="Rejected Status Paper",
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

    summary = paper.run_one_tick(
        run_id=run_id,
        strategy=strategy,
        strategy_status=StrategyStatus.DISABLED,
    )

    with session_scope(engine) as session:
        order = session.scalar(select(PaperOrderORM).where(PaperOrderORM.run_id == run_id))
        risk_decision = session.scalar(select(RiskDecisionORM).where(RiskDecisionORM.run_id == run_id))
        ledger_rows = session.scalars(
            select(CashLedgerORM)
            .where(CashLedgerORM.account_id == account_id)
            .order_by(CashLedgerORM.id)
        ).all()

    assert summary.orders_created == 1
    assert summary.orders_filled == 0
    assert summary.orders_rejected == 1
    assert summary.fills_created == 0
    assert summary.risk_decision_count == 1
    assert order.status == "risk_rejected"
    assert order.risk_decision == "rejected"
    assert risk_decision.order_id == order.id
    assert risk_decision.decision == "rejected"
    assert persisted_counts(engine, account_id, run_id) == {
        "orders": 1,
        "fills": 0,
        "positions": 0,
        "ledger": 1,
        "snapshots": 1,
        "risk_decisions": 1,
    }
    assert [row.event_type for row in ledger_rows] == ["initial_deposit"]
    assert ledger_rows[0].cash_after == Decimal("100000")


def test_insufficient_cash_marks_order_skipped_without_cash_or_position_change(
    legacy_sqlite_db: Path,
):
    paper, engine = make_paper_engine(legacy_sqlite_db)
    strategy = OversizedBuyStrategy()
    account_id = paper.create_account(
        name="Insufficient Cash Paper",
        initial_cash=Decimal("100"),
        base_currency="CNY",
    )
    run_id = paper.start_run(
        account_id=account_id,
        symbol="000001",
        strategy=strategy,
        strategy_name=strategy.name,
        strategy_status=StrategyStatus.APPROVED,
    )

    summary = paper.run_one_tick(
        run_id=run_id,
        strategy=strategy,
        strategy_status=StrategyStatus.APPROVED,
    )

    with session_scope(engine) as session:
        order = session.scalar(select(PaperOrderORM).where(PaperOrderORM.run_id == run_id))
        risk_decision = session.scalar(select(RiskDecisionORM).where(RiskDecisionORM.run_id == run_id))
        ledger_rows = session.scalars(
            select(CashLedgerORM)
            .where(CashLedgerORM.account_id == account_id)
            .order_by(CashLedgerORM.id)
        ).all()

    assert summary.orders_created == 1
    assert summary.orders_filled == 0
    assert summary.orders_rejected == 0
    assert summary.fills_created == 0
    assert summary.risk_decision_count == 1
    assert order.status == "skipped"
    assert order.risk_decision == "approved"
    assert risk_decision.order_id == order.id
    assert risk_decision.decision == "approved"
    assert persisted_counts(engine, account_id, run_id) == {
        "orders": 1,
        "fills": 0,
        "positions": 0,
        "ledger": 1,
        "snapshots": 1,
        "risk_decisions": 1,
    }
    assert [row.event_type for row in ledger_rows] == ["initial_deposit"]
    assert ledger_rows[0].cash_after == Decimal("100")


def test_sell_to_zero_retains_position_row_for_audit(legacy_sqlite_db: Path):
    paper, engine = make_paper_engine(legacy_sqlite_db)
    buy_strategy = RecordingBuyStrategy()
    account_id = paper.create_account(
        name="Sell To Zero Paper",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )
    run_id = paper.start_run(
        account_id=account_id,
        symbol="000001",
        strategy=buy_strategy,
        strategy_name=buy_strategy.name,
        strategy_status=StrategyStatus.APPROVED,
    )
    paper.run_one_tick(
        run_id=run_id,
        strategy=buy_strategy,
        strategy_status=StrategyStatus.APPROVED,
    )
    add_later_bar(engine)

    sell_strategy = SellAllStrategy(name=buy_strategy.name)
    summary = paper.run_one_tick(
        run_id=run_id,
        strategy=sell_strategy,
        strategy_status=StrategyStatus.APPROVED,
    )

    with session_scope(engine) as session:
        position = session.scalar(
            select(PaperPositionORM).where(PaperPositionORM.account_id == account_id)
        )
        ledger_rows = session.scalars(
            select(CashLedgerORM)
            .where(CashLedgerORM.account_id == account_id)
            .order_by(CashLedgerORM.id)
        ).all()
        fill = session.scalar(
            select(PaperFillORM)
            .where(PaperFillORM.run_id == run_id, PaperFillORM.side == OrderSide.SELL.value)
        )
        loaded_portfolio = PaperStateRepository(session).load_portfolio(account_id)

    assert summary.orders_created == 1
    assert summary.orders_filled == 1
    assert summary.orders_rejected == 0
    assert summary.fills_created == 1
    assert position.quantity == 0
    assert position.realized_pnl != Decimal("0")
    assert fill.side == "sell"
    assert loaded_portfolio.positions == {}
    assert loaded_portfolio.realized_pnl == position.realized_pnl
    assert [row.event_type for row in ledger_rows] == [
        "initial_deposit",
        "buy_notional",
        "commission",
        "sell_notional",
        "commission",
    ]
    assert ledger_rows[3].amount == fill.price * Decimal(fill.quantity)
    assert ledger_rows[4].amount == -fill.commission


def test_paper_tick_with_dry_run_broker_records_order_without_fill_or_position(
    legacy_sqlite_db: Path,
):
    from quant_trading.execution.broker import DryRunBrokerAdapter

    paper, engine = make_paper_engine(legacy_sqlite_db)
    dry_run_broker = DryRunBrokerAdapter()
    paper.broker = dry_run_broker
    strategy = RecordingBuyStrategy()
    account_id = paper.create_account(
        name="Dry Run Paper",
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

    summary = paper.run_one_tick(
        run_id=run_id,
        strategy=strategy,
        strategy_status=StrategyStatus.APPROVED,
    )

    with session_scope(engine) as session:
        order = session.scalar(select(PaperOrderORM).where(PaperOrderORM.run_id == run_id))
        fill_count = session.scalar(
            select(func.count()).select_from(PaperFillORM).where(PaperFillORM.run_id == run_id)
        )
        position_count = session.scalar(
            select(func.count())
            .select_from(PaperPositionORM)
            .where(PaperPositionORM.account_id == account_id)
        )
        broker_events = BrokerOrderEventRepository(session).list_for_run(run_id)

    assert summary.orders_created == 1
    assert summary.orders_filled == 0
    assert summary.fills_created == 0
    assert order.status == "skipped"
    assert order.risk_decision == "approved"
    assert fill_count == 0
    assert position_count == 0
    assert len(dry_run_broker.submitted_requests) == 1
    assert len(broker_events) == 1
    assert broker_events[0].broker_mode == "dry_run"
    assert broker_events[0].status == "submitted"
    assert broker_events[0].accepted is True
    assert json.loads(broker_events[0].result_payload)["has_fill"] is False
