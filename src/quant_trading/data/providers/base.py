from typing import Protocol

from quant_trading.core.models import Bar


class MarketDataProvider(Protocol):
    name: str

    def fetch_daily_bars(self, symbol: str, start: str | None, end: str | None) -> list[Bar]:
        raise NotImplementedError
