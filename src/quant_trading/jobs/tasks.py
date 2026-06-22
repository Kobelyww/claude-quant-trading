from decimal import Decimal
from pathlib import Path

from quant_trading.backtest.engine import BacktestEngine
from quant_trading.core.enums import StrategyStatus
from quant_trading.paper.engine import PaperTradingEngine
from quant_trading.risk.engine import RiskEngine
from quant_trading.risk.rules import (
    MaxOrderValueRule,
    NoTradeWithoutDataRule,
    PriceSanityRule,
    StrategyStatusRule,
)
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


def run_paper_tick_task(database_url: str, run_id: int) -> dict:
    engine = make_engine(database_url)
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
    result = paper.run_one_tick(
        run_id=run_id,
        strategy=MACrossStrategy(short_window=5, long_window=20, order_size=100),
        strategy_status=StrategyStatus.APPROVED,
    )
    return {
        "run_id": result.run_id,
        "account_id": result.account_id,
        "processed_at": result.processed_at.isoformat(),
        "orders_created": result.orders_created,
        "orders_filled": result.orders_filled,
        "orders_rejected": result.orders_rejected,
        "fills_created": result.fills_created,
        "snapshot_created": result.snapshot_created,
        "risk_decision_count": result.risk_decision_count,
        "idempotent_noop": result.idempotent_noop,
    }
