from datetime import date, timedelta
from decimal import Decimal

from quant_trading.core.enums import Market, OrderSide
from quant_trading.core.models import Bar, Portfolio
from quant_trading.strategy.builtin.ma_cross import MACrossStrategy
from quant_trading.strategy.registry import StrategyRegistry


def make_bar(day: int, close: str) -> Bar:
    price = Decimal(close)
    return Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=date(2026, 1, 1) + timedelta(days=day),
        open=price,
        high=price + Decimal("0.5"),
        low=price - Decimal("0.5"),
        close=price,
        volume=Decimal("100000"),
    )


def test_ma_cross_generates_buy_on_bullish_cross():
    bars = [
        make_bar(0, "10"),
        make_bar(1, "10"),
        make_bar(2, "10"),
        make_bar(3, "11"),
    ]
    strategy = MACrossStrategy(short_window=2, long_window=3, order_size=100)
    portfolio = Portfolio(account_id=1, cash=Decimal("100000"))

    intents = strategy.on_bar(bars=bars, portfolio=portfolio)

    assert len(intents) == 1
    assert intents[0].side is OrderSide.BUY
    assert intents[0].quantity == 100
    assert intents[0].reason == "ma_cross_bullish"


def test_ma_cross_does_not_repeat_buy_after_cross_bar():
    bars = [
        make_bar(0, "10"),
        make_bar(1, "10"),
        make_bar(2, "10"),
        make_bar(3, "11"),
        make_bar(4, "12"),
    ]
    strategy = MACrossStrategy(short_window=2, long_window=3, order_size=100)
    portfolio = Portfolio(account_id=1, cash=Decimal("100000"))

    intents = strategy.on_bar(bars=bars, portfolio=portfolio)

    assert intents == []


def test_strategy_registry_returns_approved_builtin_strategy():
    registry = StrategyRegistry()
    registry.register_builtin("ma_cross", MACrossStrategy)

    strategy = registry.create("ma_cross", {"short_window": 2, "long_window": 3})

    assert isinstance(strategy, MACrossStrategy)
