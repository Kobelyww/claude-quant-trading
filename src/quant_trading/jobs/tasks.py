from decimal import Decimal
from pathlib import Path

from quant_trading.backtest.engine import BacktestEngine
from quant_trading.storage.db import create_all, make_engine
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.strategy.builtin.ma_cross import MACrossStrategy


def import_legacy_data_task(legacy_db_path: str, database_url: str) -> dict:
    engine = make_engine(database_url)
    create_all(engine)
    result = import_legacy_sqlite(Path(legacy_db_path), engine)
    return {
        "imported_symbols": result.imported_symbols,
        "imported_bars": result.imported_bars,
    }


def run_ma_cross_backtest_task(database_url: str, symbol: str = "000001") -> dict:
    engine = make_engine(database_url)
    backtest = BacktestEngine(
        engine=engine,
        initial_cash=Decimal("100000"),
        commission_rate=Decimal("0.0003"),
        slippage_rate=Decimal("0.001"),
    )
    result = backtest.run(
        symbol=symbol,
        strategy=MACrossStrategy(short_window=5, long_window=20, order_size=100),
        strategy_name="ma_cross",
    )
    return {
        "run_id": result.run_id,
        "final_equity": str(result.final_equity),
        "equity_points": result.equity_points,
    }
