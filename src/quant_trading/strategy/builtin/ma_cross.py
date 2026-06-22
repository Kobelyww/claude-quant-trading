from decimal import Decimal

from quant_trading.core.enums import OrderSide
from quant_trading.core.models import Bar, OrderIntent, Portfolio


class MACrossStrategy:
    name = "ma_cross"

    def __init__(self, short_window: int = 5, long_window: int = 20, order_size: int = 100):
        if short_window <= 0 or long_window <= 0:
            raise ValueError("windows must be positive")
        if short_window >= long_window:
            raise ValueError("short_window must be less than long_window")
        if order_size <= 0:
            raise ValueError("order_size must be positive")
        self.short_window = short_window
        self.long_window = long_window
        self.order_size = order_size

    def on_bar(self, bars: list[Bar], portfolio: Portfolio) -> list[OrderIntent]:
        if len(bars) < self.long_window + 1:
            return []

        closes = [bar.close for bar in bars]
        previous_short = self._mean(closes[-self.short_window - 1 : -1])
        previous_long = self._mean(closes[-self.long_window - 1 : -1])
        current_short = self._mean(closes[-self.short_window :])
        current_long = self._mean(closes[-self.long_window :])
        latest = bars[-1]
        has_position = latest.instrument_id in portfolio.positions and portfolio.positions[latest.instrument_id].quantity > 0

        if previous_short <= previous_long and current_short > current_long and not has_position:
            return [
                OrderIntent(
                    instrument_id=latest.instrument_id,
                    symbol=latest.symbol,
                    side=OrderSide.BUY,
                    quantity=self.order_size,
                    reason="ma_cross_bullish",
                )
            ]
        if previous_short >= previous_long and current_short < current_long and has_position:
            quantity = portfolio.positions[latest.instrument_id].quantity
            return [
                OrderIntent(
                    instrument_id=latest.instrument_id,
                    symbol=latest.symbol,
                    side=OrderSide.SELL,
                    quantity=quantity,
                    reason="ma_cross_bearish",
                )
            ]
        return []

    def _mean(self, values: list[Decimal]) -> Decimal:
        return sum(values, Decimal("0")) / Decimal(len(values))
