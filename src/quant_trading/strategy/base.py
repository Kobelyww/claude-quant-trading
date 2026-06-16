from typing import Protocol

from quant_trading.core.models import Bar, OrderIntent, Portfolio


class Strategy(Protocol):
    name: str

    def on_bar(self, bars: list[Bar], portfolio: Portfolio) -> list[OrderIntent]:
        raise NotImplementedError
