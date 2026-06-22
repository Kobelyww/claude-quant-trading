from pathlib import Path

from quant_trading.storage.db import create_all, make_engine
from quant_trading.workflows import import_legacy_data, run_ma_cross_backtest, run_paper_tick


def import_legacy_data_task(legacy_db_path: str, database_url: str) -> dict:
    engine = make_engine(database_url)
    create_all(engine)
    return import_legacy_data(engine, Path(legacy_db_path))


def run_ma_cross_backtest_task(database_url: str, symbol: str = "000001") -> dict:
    engine = make_engine(database_url)
    create_all(engine)
    return run_ma_cross_backtest(
        engine,
        symbol=symbol,
        short_window=5,
        long_window=20,
        order_size=100,
        initial_cash="100000",
    )


def run_paper_tick_task(database_url: str, run_id: int) -> dict:
    engine = make_engine(database_url)
    create_all(engine)
    return run_paper_tick(engine, run_id)
