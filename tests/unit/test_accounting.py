from datetime import date
from decimal import Decimal

from quant_trading.core.enums import Market, OrderSide
from quant_trading.core.models import Bar, OrderIntent, Portfolio
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
