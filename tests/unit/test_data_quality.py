from datetime import date, timedelta
from decimal import Decimal

from quant_trading.core.enums import Adjustment, Market
from quant_trading.core.models import Bar
from quant_trading.data.quality import assess_bars_quality


def make_bar(
    day: date,
    close: Decimal = Decimal("10"),
    volume: Decimal = Decimal("1000"),
) -> Bar:
    return Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=day,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=volume,
        source="akshare",
        adjusted=Adjustment.QFQ,
    )


def test_assess_bars_quality_passes_clean_data():
    start = date(2026, 1, 1)
    bars = [make_bar(start + timedelta(days=day)) for day in range(120)]

    report = assess_bars_quality(
        bars,
        requested_start=start,
        requested_end=start + timedelta(days=119),
        now=date(2026, 5, 10),
    )

    assert report["status"] == "passed"
    assert report["severity"] == "none"
    assert report["bar_count"] == 120
    assert len(report["data_fingerprint"]) == 64


def test_assess_bars_quality_fails_duplicate_timestamps():
    start = date(2026, 1, 1)
    bars = [make_bar(start + timedelta(days=day)) for day in range(120)]
    bars.append(make_bar(start))

    report = assess_bars_quality(
        bars,
        requested_start=start,
        requested_end=start + timedelta(days=119),
        now=date(2026, 5, 10),
    )

    assert report["duplicate_timestamp_count"] == 1
    assert report["status"] == "failed"
    assert report["severity"] == "high"


def test_assess_bars_quality_fails_non_positive_prices():
    start = date(2026, 1, 1)
    bars = [make_bar(start + timedelta(days=day)) for day in range(120)]
    bars[0] = make_bar(start, close=Decimal("0"))

    report = assess_bars_quality(
        bars,
        requested_start=start,
        requested_end=start + timedelta(days=119),
        now=date(2026, 5, 10),
    )

    assert report["non_positive_price_count"] == 1
    assert report["status"] == "failed"
    assert report["severity"] == "high"


def test_assess_bars_quality_fails_invalid_ohlc():
    start = date(2026, 1, 1)
    bars = [make_bar(start + timedelta(days=day)) for day in range(120)]
    object.__setattr__(bars[0], "high", Decimal("8"))

    report = assess_bars_quality(
        bars,
        requested_start=start,
        requested_end=start + timedelta(days=119),
        now=date(2026, 5, 10),
    )

    assert report["invalid_ohlc_count"] == 1
    assert report["status"] == "failed"
    assert report["severity"] == "high"


def test_assess_bars_quality_flags_medium_missing_coverage():
    start = date(2026, 1, 1)
    weekdays = [
        start + timedelta(days=day)
        for day in range(180)
        if (start + timedelta(days=day)).weekday() < 5
    ]
    bars = [make_bar(day) for index, day in enumerate(weekdays) if index >= 8]

    report = assess_bars_quality(
        bars,
        requested_start=start,
        requested_end=start + timedelta(days=179),
        now=date(2026, 5, 10),
    )

    assert report["missing_bar_count"] == 8
    assert report["status"] == "needs_review"
    assert report["severity"] == "medium"


def test_assess_bars_quality_handles_zero_expected_count_without_division_error():
    report = assess_bars_quality(
        [],
        requested_start=None,
        requested_end=None,
        now=date(2026, 1, 1),
    )

    assert report["expected_bar_count"] == 0
    assert report["status"] in {"failed", "needs_review"}


def test_data_fingerprint_is_stable_and_changes_when_values_change():
    start = date(2026, 1, 1)
    bars = [make_bar(start + timedelta(days=day)) for day in range(120)]
    reordered = list(reversed(bars))
    changed = list(bars)
    changed[0] = make_bar(start, close=Decimal("11"))

    first = assess_bars_quality(
        bars,
        requested_start=start,
        requested_end=start + timedelta(days=119),
        now=date(2026, 5, 10),
    )
    second = assess_bars_quality(
        reordered,
        requested_start=start,
        requested_end=start + timedelta(days=119),
        now=date(2026, 5, 10),
    )
    third = assess_bars_quality(
        changed,
        requested_start=start,
        requested_end=start + timedelta(days=119),
        now=date(2026, 5, 10),
    )

    assert first["data_fingerprint"] == second["data_fingerprint"]
    assert first["data_fingerprint"] != third["data_fingerprint"]
