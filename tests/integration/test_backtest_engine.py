from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import (
    BacktestEquityPointORM,
    BacktestFillORM,
    BacktestOrderORM,
    BacktestRunORM,
)
from quant_trading.strategy.builtin.ma_cross import MACrossStrategy
from tests.integration.test_legacy_migration import _build_legacy_sample


def test_backtest_persists_equity_orders_and_fills(tmp_path: Path):
    from quant_trading.backtest.engine import BacktestEngine

    legacy_db = tmp_path / "legacy.sqlite3"
    _build_legacy_sample(legacy_db)

    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_db, engine)

    backtest = BacktestEngine(
        engine=engine,
        initial_cash=Decimal("100000"),
        commission_rate=Decimal("0.0003"),
        slippage_rate=Decimal("0.001"),
    )

    result = backtest.run(
        symbol="000001",
        strategy=MACrossStrategy(short_window=5, long_window=20, order_size=100),
        strategy_name="ma_cross",
    )

    with session_scope(engine) as session:
        run = session.scalar(select(BacktestRunORM).where(BacktestRunORM.id == result.run_id))
        equity_points = session.scalars(
            select(BacktestEquityPointORM).where(BacktestEquityPointORM.run_id == result.run_id)
        ).all()
        orders = session.scalars(
            select(BacktestOrderORM).where(BacktestOrderORM.run_id == result.run_id)
        ).all()
        fills = session.scalars(
            select(BacktestFillORM).where(BacktestFillORM.run_id == result.run_id)
        ).all()

    assert result.run_id > 0
    assert result.final_equity > Decimal("0")
    assert result.equity_points >= 100
    assert result.order_count == len(orders)
    assert result.fill_count == len(fills)
    assert run is not None
    assert run.final_equity == result.final_equity
    assert run.status == "done"
    assert len(equity_points) == result.equity_points
