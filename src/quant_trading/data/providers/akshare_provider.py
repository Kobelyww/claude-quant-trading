from decimal import Decimal

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.data.validation import validate_bars


class AkshareProvider:
    name = "akshare"

    def fetch_daily_bars(
        self,
        instrument_id: int,
        symbol: str,
        start: str | None,
        end: str | None,
    ) -> list[Bar]:
        import akshare as ak

        exchange_symbol = self._exchange_symbol(symbol)
        df = ak.stock_zh_a_hist_tx(
            symbol=exchange_symbol,
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        bars = [
            Bar(
                instrument_id=instrument_id,
                symbol=symbol,
                market=Market.A_STOCK,
                timestamp=row["date"],
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row.get("volume", row.get("amount", 0)))),
                source=self.name,
            )
            for _, row in df.iterrows()
        ]
        return validate_bars(bars)

    def _exchange_symbol(self, symbol: str) -> str:
        code = symbol.zfill(6)
        if code.startswith(("600", "601", "603", "605", "688")):
            return f"sh{code}"
        return f"sz{code}"
