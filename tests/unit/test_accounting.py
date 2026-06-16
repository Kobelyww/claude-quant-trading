from datetime import date
from decimal import Decimal

import pytest

from quant_trading.core.enums import Market, OrderSide
from quant_trading.core.models import Bar, Fill, OrderIntent, Portfolio
from quant_trading.execution.simulator import SimulatedBroker
from quant_trading.portfolio.accounting import apply_fill


def test_buy_fill_reduces_cash_and_creates_position():
    bar = Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=date(2026, 5, 8),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=Decimal("100000"),
    )
    portfolio = Portfolio(account_id=1, cash=Decimal("100000"))
    broker = SimulatedBroker(commission_rate=Decimal("0.0003"), slippage_rate=Decimal("0.001"))
    intent = OrderIntent(
        instrument_id=1,
        symbol="000001",
        side=OrderSide.BUY,
        quantity=100,
        reason="test",
    )

    fill = broker.execute_market_order(intent, bar)
    updated = apply_fill(portfolio, fill)

    assert fill.price == Decimal("10.010")
    assert fill.commission == Decimal("0.300300")
    assert updated.positions[1].quantity == 100
    assert updated.cash == Decimal("98998.699700")


def test_round_trip_realized_pnl_includes_buy_and_sell_commissions():
    portfolio = Portfolio(account_id=1, cash=Decimal("10000"))

    buy_fill = Fill(
        order_id=None,
        instrument_id=1,
        symbol="000001",
        side=OrderSide.BUY,
        quantity=100,
        price=Decimal("10"),
        commission=Decimal("1.0"),
        slippage=Decimal("0"),
        filled_at=date(2026, 5, 8),
    )
    after_buy = apply_fill(portfolio, buy_fill)

    sell_fill = Fill(
        order_id=None,
        instrument_id=1,
        symbol="000001",
        side=OrderSide.SELL,
        quantity=100,
        price=Decimal("11"),
        commission=Decimal("1.1"),
        slippage=Decimal("0"),
        filled_at=date(2026, 5, 9),
    )
    after_sell = apply_fill(after_buy, sell_fill)

    assert after_sell.realized_pnl == Decimal("97.9")


def test_buy_fill_rejects_when_cash_would_go_negative():
    portfolio = Portfolio(account_id=1, cash=Decimal("100"))
    fill = Fill(
        order_id=None,
        instrument_id=1,
        symbol="000001",
        side=OrderSide.BUY,
        quantity=11,
        price=Decimal("10"),
        commission=Decimal("0.1"),
        slippage=Decimal("0"),
        filled_at=date(2026, 5, 8),
    )

    with pytest.raises(ValueError, match="insufficient cash for buy fill"):
        apply_fill(portfolio, fill)
