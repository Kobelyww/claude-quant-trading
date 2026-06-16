from decimal import Decimal

from quant_trading.core.enums import Market, OrderSide, OrderStatus, OrderType
from quant_trading.core.models import Bar, OrderIntent, Portfolio, Position


def test_bar_rejects_invalid_ohlc():
    try:
        Bar(
            instrument_id=1,
            symbol="000001",
            market=Market.A_STOCK,
            timestamp="2026-05-08",
            open=Decimal("10"),
            high=Decimal("9"),
            low=Decimal("8"),
            close=Decimal("8.5"),
            volume=Decimal("1000"),
        )
    except ValueError as exc:
        assert "high must be greater than or equal to open/close/low" in str(exc)
    else:
        raise AssertionError("invalid OHLC should fail")


def test_order_intent_defaults_to_created_market_buy():
    intent = OrderIntent(
        instrument_id=1,
        symbol="000001",
        side=OrderSide.BUY,
        quantity=100,
        reason="ma_cross_entry",
    )

    assert intent.order_type is OrderType.MARKET
    assert intent.status is OrderStatus.CREATED
    assert intent.quantity == 100


def test_portfolio_equity_includes_cash_and_positions():
    portfolio = Portfolio(
        account_id=1,
        cash=Decimal("10000"),
        positions={
            1: Position(
                instrument_id=1,
                symbol="000001",
                quantity=200,
                avg_cost=Decimal("9.50"),
                market_price=Decimal("10.00"),
            )
        },
    )

    assert portfolio.market_value == Decimal("2000.00")
    assert portfolio.equity == Decimal("12000.00")
