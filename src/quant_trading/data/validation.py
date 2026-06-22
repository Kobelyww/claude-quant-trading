from quant_trading.core.models import Bar


def validate_bars(bars: list[Bar]) -> list[Bar]:
    seen: set[tuple[int, object]] = set()
    for bar in bars:
        key = (bar.instrument_id, bar.timestamp)
        if key in seen:
            raise ValueError(f"duplicate bar for instrument_id={bar.instrument_id} timestamp={bar.timestamp}")
        seen.add(key)
    return sorted(bars, key=lambda b: b.timestamp)
