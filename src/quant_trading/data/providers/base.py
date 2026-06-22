from typing import Protocol

from quant_trading.core.models import Bar


class MarketDataProvider(Protocol):
    name: str

    def fetch_daily_bars(
        self,
        instrument_id: int,
        symbol: str,
        start: str | None,
        end: str | None,
    ) -> list[Bar]:
        raise NotImplementedError
