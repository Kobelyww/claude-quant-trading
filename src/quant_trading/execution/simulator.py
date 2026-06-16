from decimal import Decimal

from quant_trading.core.models import Bar, Fill, OrderIntent
from quant_trading.execution.commission import percent_commission
from quant_trading.execution.slippage import apply_percent_slippage


class SimulatedBroker:
    def __init__(self, commission_rate: Decimal, slippage_rate: Decimal):
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate

    def execute_market_order(self, intent: OrderIntent, bar: Bar) -> Fill:
        price = apply_percent_slippage(bar.close, intent.side, self.slippage_rate)
        notional = price * Decimal(intent.quantity)
        commission = percent_commission(notional, self.commission_rate)
        slippage = abs(price - bar.close) * Decimal(intent.quantity)
        return Fill(
            order_id=None,
            instrument_id=intent.instrument_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            price=price,
            commission=commission,
            slippage=slippage,
            filled_at=bar.timestamp,
        )
