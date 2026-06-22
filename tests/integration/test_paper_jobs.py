from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from quant_trading.core.enums import StrategyStatus
from quant_trading.jobs import tasks
from quant_trading.jobs.tasks import run_paper_tick_task
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
from quant_trading.storage.models import (
    CashLedgerORM,
    PaperFillORM,
    PaperOrderORM,
    PortfolioSnapshotORM,
    RiskDecisionORM,
)
from quant_trading.strategy.builtin.ma_cross import MACrossStrategy
from quant_trading.workflows import operations


def persisted_counts(engine, account_id: int, run_id: int) -> dict[str, int]:
    with session_scope(engine) as session:
        return {
            "orders": session.scalar(
                select(func.count()).select_from(PaperOrderORM).where(PaperOrderORM.run_id == run_id)
            ),
            "fills": session.scalar(
                select(func.count()).select_from(PaperFillORM).where(PaperFillORM.run_id == run_id)
            ),
            "snapshots": session.scalar(
                select(func.count())
                .select_from(PortfolioSnapshotORM)
                .where(
                    PortfolioSnapshotORM.account_id == account_id,
                    PortfolioSnapshotORM.run_id == run_id,
                )
            ),
            "risk_decisions": session.scalar(
                select(func.count())
                .select_from(RiskDecisionORM)
                .where(RiskDecisionORM.run_id == run_id)
            ),
            "ledger": session.scalar(
                select(func.count())
                .select_from(CashLedgerORM)
                .where(CashLedgerORM.account_id == account_id)
            ),
        }


def test_run_paper_tick_task_runs_existing_paper_run(legacy_sqlite_db: Path, tmp_path: Path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'paper.sqlite3'}"
    engine = make_engine(database_url)
    create_all(engine)
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
    strategy = MACrossStrategy(short_window=5, long_window=20, order_size=100)
    account_id = paper.create_account(
        name="Job Paper",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )
    run_id = paper.start_run(
        account_id=account_id,
        symbol="000001",
        strategy=strategy,
        strategy_name="ma_cross",
        strategy_status=StrategyStatus.APPROVED,
    )

    result = run_paper_tick_task(database_url=database_url, run_id=run_id)

    with session_scope(engine) as session:
        fills = session.scalars(select(PaperFillORM).where(PaperFillORM.run_id == run_id)).all()

    assert result["run_id"] == run_id
    assert result["account_id"] == account_id
    assert result["idempotent_noop"] is False
    assert result["snapshot_created"] is True
    assert len(fills) == result["fills_created"]

    counts_after_first = persisted_counts(engine, account_id, run_id)
    second = run_paper_tick_task(database_url=database_url, run_id=run_id)

    assert second["idempotent_noop"] is True
    assert second["snapshot_created"] is False
    assert second["orders_created"] == 0
    assert second["orders_filled"] == 0
    assert second["orders_rejected"] == 0
    assert second["fills_created"] == 0
    assert second["risk_decision_count"] == 0
    assert second["processed_at"] == result["processed_at"]
    assert persisted_counts(engine, account_id, run_id) == counts_after_first


def test_run_paper_tick_task_uses_persisted_ma_cross_config(
    legacy_sqlite_db: Path,
    tmp_path: Path,
    monkeypatch,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'paper-custom.sqlite3'}"
    engine = make_engine(database_url)
    create_all(engine)
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
    account_id = paper.create_account(
        name="Job Custom Paper",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )
    run_id = paper.start_run(
        account_id=account_id,
        symbol="000001",
        strategy=MACrossStrategy(short_window=3, long_window=8, order_size=250),
        strategy_name="ma_cross",
        strategy_status=StrategyStatus.APPROVED,
    )
    observed_init_kwargs = {}

    class SpyMACrossStrategy(MACrossStrategy):
        def __init__(self, short_window=5, long_window=20, order_size=100):
            observed_init_kwargs.update(
                {
                    "short_window": short_window,
                    "long_window": long_window,
                    "order_size": order_size,
                }
            )
            super().__init__(
                short_window=short_window,
                long_window=long_window,
                order_size=order_size,
            )

    monkeypatch.setattr(operations, "MACrossStrategy", SpyMACrossStrategy)

    run_paper_tick_task(database_url=database_url, run_id=run_id)

    assert observed_init_kwargs == {
        "short_window": 3,
        "long_window": 8,
        "order_size": 250,
    }


def test_run_paper_tick_task_rejects_unsupported_strategy(tmp_path: Path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'paper-unsupported.sqlite3'}"
    engine = make_engine(database_url)
    create_all(engine)

    paper = PaperTradingEngine(
        engine=engine,
        initial_cash=Decimal("100000"),
        risk_engine=RiskEngine([]),
    )
    account_id = paper.create_account(
        name="Job Unsupported Paper",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )
    run_id = paper.start_run(
        account_id=account_id,
        symbol="000001",
        strategy=type("UnsupportedStrategy", (), {"name": "custom_strategy"})(),
        strategy_name="custom_strategy",
        strategy_status=StrategyStatus.APPROVED,
    )

    with pytest.raises(ValueError, match="unsupported paper strategy for job: custom_strategy"):
        run_paper_tick_task(database_url=database_url, run_id=run_id)
