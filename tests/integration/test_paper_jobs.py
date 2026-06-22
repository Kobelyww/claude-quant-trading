from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from quant_trading.core.enums import StrategyStatus
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
from quant_trading.storage.models import PaperFillORM
from quant_trading.strategy.builtin.ma_cross import MACrossStrategy


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
