from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from quant_trading.backtest.engine import BacktestEngine
from quant_trading.core.enums import OrderSide
from quant_trading.core.models import OrderIntent
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import (
    BacktestEquityPointORM,
    BacktestFillORM,
    BacktestOrderORM,
    BacktestRunORM,
)
from quant_trading.strategy.builtin.ma_cross import MACrossStrategy


def test_backtest_persists_equity_orders_and_fills(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)

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


class InvalidSellStrategy:
    name = "invalid_sell"

    def on_bar(self, bars, portfolio):
        if len(bars) == 1:
            latest = bars[-1]
            return [
                OrderIntent(
                    instrument_id=latest.instrument_id,
                    symbol=latest.symbol,
                    side=OrderSide.SELL,
                    quantity=100,
                    reason="invalid_sell_without_position",
                )
            ]
        return []


def test_backtest_does_not_swallow_accounting_errors(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)

    backtest = BacktestEngine(
        engine=engine,
        initial_cash=Decimal("100000"),
        commission_rate=Decimal("0.0003"),
        slippage_rate=Decimal("0.001"),
    )

    try:
        backtest.run(
            symbol="000001",
            strategy=InvalidSellStrategy(),
            strategy_name="invalid_sell",
        )
    except ValueError as exc:
        assert "cannot sell more shares than the portfolio holds" in str(exc)
    else:
        raise AssertionError("invalid sell accounting error should not be swallowed")
