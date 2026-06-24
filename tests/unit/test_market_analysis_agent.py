from datetime import date, timedelta
from decimal import Decimal

from quant_trading.agents.llm import FakeLLMClient
from quant_trading.agents.market_analysis import build_market_analysis_prompt, compute_market_metrics
from quant_trading.agents.models import MarketAnalysisRequest
from quant_trading.core.enums import Market
from quant_trading.core.models import Bar


def make_bars(count=121):
    start = date(2026, 1, 1)
    bars = []
    for index in range(count):
        close = Decimal("10") + Decimal(index) / Decimal("10")
        bars.append(
            Bar(
                instrument_id=1,
                symbol="000001",
                market=Market.A_STOCK,
                timestamp=start + timedelta(days=index),
                open=close - Decimal("0.1"),
                high=close + Decimal("0.2"),
                low=close - Decimal("0.2"),
                close=close,
                volume=Decimal("100000") + Decimal(index),
                source="test",
            )
        )
    return bars


def test_compute_market_metrics_from_known_bars():
    metrics = compute_market_metrics(make_bars(), MarketAnalysisRequest(symbol="000001"))

    assert metrics["symbol"] == "000001"
    assert metrics["bar_count"] == 121
    assert metrics["start"] == "2026-01-01"
    assert metrics["end"] == "2026-05-01"
    assert metrics["latest_close"] == "22"
    assert metrics["trend_direction"] == "up"
    assert metrics["volatility_regime"] in {"low", "normal", "high"}
    assert metrics["high_52w"] is None
    assert metrics["low_52w"] is None
    assert "max_drawdown" in metrics


def test_market_analysis_prompt_contains_safety_constraints():
    metrics = compute_market_metrics(make_bars(), MarketAnalysisRequest(symbol="000001"))

    prompt = build_market_analysis_prompt(metrics, mode="overview", max_chars=8000)

    assert "historical data only" in prompt
    assert "Do not provide buy or sell recommendations" in prompt
    assert "Do not predict future prices" in prompt
    assert "Chinese" in prompt
    assert "000001" in prompt


def test_fake_llm_is_usable_for_market_analysis_prompt():
    llm = FakeLLMClient("研究报告")

    response = llm.complete("prompt")

    assert response.content == "研究报告"
