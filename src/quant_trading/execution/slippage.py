from decimal import Decimal

from quant_trading.core.enums import OrderSide


def apply_percent_slippage(price: Decimal, side: OrderSide, rate: Decimal) -> Decimal:
    if side is OrderSide.BUY:
        return price * (Decimal("1") + rate)
    return price * (Decimal("1") - rate)
