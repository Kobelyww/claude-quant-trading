from __future__ import annotations

from decimal import Decimal
import json

from quant_trading.agents.models import MarketAnalysisRequest
from quant_trading.core.models import Bar


def compute_market_metrics(
    bars: list[Bar],
    request: MarketAnalysisRequest,
) -> dict[str, str | int | None]:
    if not bars:
        raise ValueError(f"no market bars found for symbol: {request.symbol}")
    if len(bars) < 60:
        raise ValueError(f"insufficient bars for market analysis: required=60 actual={len(bars)}")

    selected = bars[-request.lookback_bars :]
    closes = [bar.close for bar in selected]
    volumes = [bar.volume for bar in selected]
    latest = selected[-1]
    returns = [
        (closes[index] / closes[index - 1]) - Decimal("1")
        for index in range(1, len(closes))
        if closes[index - 1] != 0
    ]
    volatility_20d = _stddev(returns[-20:]) if len(returns) >= 20 else Decimal("0")
    ma_20 = _average(closes[-20:]) if len(closes) >= 20 else closes[-1]
    ma_60 = _average(closes[-60:]) if len(closes) >= 60 else closes[0]
    trend = "up" if ma_20 > ma_60 else "down" if ma_20 < ma_60 else "flat"
    max_drawdown = _max_drawdown(closes)
    volatility_regime = (
        "high"
        if volatility_20d > Decimal("0.03")
        else "low"
        if volatility_20d < Decimal("0.01")
        else "normal"
    )

    return {
        "symbol": request.symbol,
        "mode": request.mode,
        "source": latest.source,
        "start": selected[0].timestamp.isoformat(),
        "end": selected[-1].timestamp.isoformat(),
        "bar_count": len(selected),
        "latest_close": _plain(latest.close),
        "return_1m": _window_return(closes, 21),
        "return_3m": _window_return(closes, 63),
        "volatility_20d": _plain(volatility_20d),
        "trend_direction": trend,
        "ma_20": _plain(ma_20),
        "ma_60": _plain(ma_60),
        "avg_volume_20d": _plain(_average(volumes[-20:])),
        "high_52w": _plain(max(closes[-252:])) if len(closes) >= 252 else None,
        "low_52w": _plain(min(closes[-252:])) if len(closes) >= 252 else None,
        "support_level": _plain(min(closes[-20:])),
        "resistance_level": _plain(max(closes[-20:])),
        "max_drawdown": _plain(max_drawdown),
        "volatility_regime": volatility_regime,
    }


def build_market_analysis_prompt(metrics: dict, mode: str, max_chars: int) -> str:
    prompt = f"""
You are a quantitative research analyst.
Write a concise Chinese market analysis report using historical data only.
Do not provide buy or sell recommendations.
Do not predict future prices.
Do not provide price targets or guaranteed return language.
Use confidence qualifiers such as shows, suggests, and indicates.

Mode: {mode}
Metrics:
{json.dumps(metrics, ensure_ascii=False, sort_keys=True)}

Required sections:
1. 市场概况
2. 趋势分析
3. 波动率与成交量
4. 关键价位
5. 风险因素
6. 市场状态分类
""".strip()
    return prompt[:max_chars]


def _average(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _stddev(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    mean = _average(values)
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(
        len(values)
    )
    return variance.sqrt()


def _window_return(closes: list[Decimal], window: int) -> str | None:
    if len(closes) <= window or closes[-window - 1] == 0:
        return None
    return _plain((closes[-1] / closes[-window - 1]) - Decimal("1"))


def _max_drawdown(closes: list[Decimal]) -> Decimal:
    peak = closes[0]
    worst = Decimal("0")
    for close in closes:
        if close > peak:
            peak = close
        if peak > 0:
            drawdown = (peak - close) / peak
            if drawdown > worst:
                worst = drawdown
    return worst


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")
