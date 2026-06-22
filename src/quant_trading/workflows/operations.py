from decimal import Decimal
import json
from pathlib import Path

from sqlalchemy import Engine

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
from quant_trading.storage.db import session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import PaperRunORM
from quant_trading.storage.repositories import MarketDataRepository
from quant_trading.strategy.builtin.ma_cross import MACrossStrategy

DEFAULT_COMMISSION_RATE = Decimal("0.0003")
DEFAULT_SLIPPAGE_RATE = Decimal("0.001")
DEFAULT_MAX_ORDER_VALUE = Decimal("100000")
DEFAULT_STRATEGY_NAME = "ma_cross"


def import_legacy_data(engine: Engine, legacy_db_path: str | Path) -> dict:
    result = import_legacy_sqlite(Path(legacy_db_path), engine)
    return {
        "imported_symbols": result.imported_symbols,
        "imported_bars": result.imported_bars,
    }


def run_ma_cross_backtest(
    engine: Engine,
    symbol: str,
    short_window: int,
    long_window: int,
    order_size: int,
    initial_cash: Decimal,
) -> dict:
    symbol = _validate_symbol(symbol)
    _validate_ma_cross(short_window, long_window, order_size)
    initial_cash = _validate_positive_decimal(initial_cash, "initial_cash")
    _ensure_market_bars_exist(engine, symbol)
    backtest = BacktestEngine(
        engine=engine,
        initial_cash=initial_cash,
        commission_rate=DEFAULT_COMMISSION_RATE,
        slippage_rate=DEFAULT_SLIPPAGE_RATE,
    )
    result = backtest.run(
        symbol=symbol,
        strategy=MACrossStrategy(
            short_window=short_window,
            long_window=long_window,
            order_size=order_size,
        ),
        strategy_name=DEFAULT_STRATEGY_NAME,
    )
    return {
        "run_id": result.run_id,
        "symbol": symbol,
        "strategy_name": DEFAULT_STRATEGY_NAME,
        "final_equity": _plain_decimal(result.final_equity),
        "equity_points": result.equity_points,
    }


def _ensure_market_bars_exist(engine: Engine, symbol: str) -> None:
    with session_scope(engine) as session:
        if not MarketDataRepository(session).list_bars(symbol):
            raise ValueError(f"no market bars found for symbol: {symbol}")


def create_paper_account(
    engine: Engine,
    name: str,
    initial_cash: Decimal,
    base_currency: str = "CNY",
) -> dict:
    trimmed_name = name.strip()
    if not trimmed_name:
        raise ValueError("paper account name is required")
    if len(trimmed_name) > 128:
        raise ValueError("name is too long")
    initial_cash = _validate_positive_decimal(initial_cash, "initial_cash")
    normalized_currency = base_currency.strip() if base_currency else "CNY"
    if not normalized_currency:
        normalized_currency = "CNY"
    if len(normalized_currency) > 16:
        raise ValueError("base_currency is too long")

    paper = _make_paper_engine(engine, initial_cash=initial_cash)
    account_id = paper.create_account(
        name=trimmed_name,
        initial_cash=initial_cash,
        base_currency=normalized_currency,
    )
    return {
        "account_id": account_id,
        "name": trimmed_name,
        "initial_cash": _plain_decimal(initial_cash),
        "base_currency": normalized_currency,
    }


def start_ma_cross_paper_run(
    engine: Engine,
    account_id: int,
    symbol: str,
    short_window: int,
    long_window: int,
    order_size: int,
    max_order_value: Decimal = DEFAULT_MAX_ORDER_VALUE,
) -> dict:
    symbol = _validate_symbol(symbol)
    _validate_ma_cross(short_window, long_window, order_size)
    max_order_value = _validate_positive_decimal(
        max_order_value,
        "max_order_value",
        message="max_order_value must be positive",
    )
    paper = _make_paper_engine(engine, initial_cash=Decimal("0"), max_order_value=max_order_value)
    run_id = paper.start_run(
        account_id=account_id,
        symbol=symbol,
        strategy=MACrossStrategy(
            short_window=short_window,
            long_window=long_window,
            order_size=order_size,
        ),
        strategy_name=DEFAULT_STRATEGY_NAME,
        strategy_status=StrategyStatus.APPROVED,
        risk_config={"max_order_value": _plain_decimal(max_order_value)},
    )
    return {
        "run_id": run_id,
        "account_id": account_id,
        "symbol": symbol,
        "strategy_name": DEFAULT_STRATEGY_NAME,
        "status": "running",
    }


def run_paper_tick(engine: Engine, run_id: int) -> dict:
    strategy, max_order_value = _load_paper_run_command(engine, run_id)
    paper = _make_paper_engine(
        engine,
        initial_cash=Decimal("0"),
        max_order_value=max_order_value,
    )
    result = paper.run_one_tick(
        run_id=run_id,
        strategy=strategy,
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


def _load_paper_run_command(engine: Engine, run_id: int) -> tuple[MACrossStrategy, Decimal]:
    with session_scope(engine) as session:
        run = session.get(PaperRunORM, run_id)
        if run is None:
            raise ValueError(f"paper run not found: {run_id}")
        strategy_name = run.strategy_name
        strategy_config = json.loads(run.strategy_config or "{}")
        risk_config = json.loads(run.risk_config or "{}")

    if strategy_name != DEFAULT_STRATEGY_NAME:
        raise ValueError(f"unsupported paper strategy for job: {strategy_name}")

    short_window = int(strategy_config.get("short_window", 5))
    long_window = int(strategy_config.get("long_window", 20))
    order_size = int(strategy_config.get("order_size", 100))
    _validate_ma_cross(short_window, long_window, order_size)
    max_order_value = _validate_positive_decimal(
        Decimal(str(risk_config.get("max_order_value", DEFAULT_MAX_ORDER_VALUE))),
        "max_order_value",
        message="max_order_value must be positive",
    )
    return (
        MACrossStrategy(
            short_window=short_window,
            long_window=long_window,
            order_size=order_size,
        ),
        max_order_value,
    )


def _make_paper_engine(
    engine: Engine,
    initial_cash: Decimal,
    max_order_value: Decimal = DEFAULT_MAX_ORDER_VALUE,
) -> PaperTradingEngine:
    return PaperTradingEngine(
        engine=engine,
        initial_cash=initial_cash,
        risk_engine=RiskEngine(
            [
                StrategyStatusRule(),
                NoTradeWithoutDataRule(),
                PriceSanityRule(),
                MaxOrderValueRule(max_order_value=max_order_value),
            ]
        ),
        commission_rate=DEFAULT_COMMISSION_RATE,
        slippage_rate=DEFAULT_SLIPPAGE_RATE,
    )


def _validate_ma_cross(short_window: int, long_window: int, order_size: int) -> None:
    if short_window <= 0:
        raise ValueError("short_window must be greater than 0")
    if long_window <= short_window:
        raise ValueError("long_window must be greater than short_window")
    if order_size <= 0:
        raise ValueError("order_size must be positive")


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if not symbol:
        raise ValueError("symbol is required")
    if len(symbol) > 32:
        raise ValueError("symbol is too long")
    return symbol


def _validate_positive_decimal(value: Decimal, name: str, message: str | None = None) -> Decimal:
    value = Decimal(str(value))
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value <= 0:
        raise ValueError(message or f"{name} must be greater than 0")
    return value


def _plain_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
