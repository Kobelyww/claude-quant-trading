from datetime import date, timedelta
from decimal import Decimal

from quant_trading.core.enums import Adjustment, Market
from quant_trading.core.models import Bar
from quant_trading.data.quality import assess_bars_quality, build_data_quality_report
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import MarketBarORM
from quant_trading.storage.repositories import (
    DataQualityReportRepository,
    InstrumentRepository,
)


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


def weekdays_from(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def test_assess_bars_quality_passes_clean_data():
    start = date(2026, 1, 1)
    weekdays = weekdays_from(start, 120)
    bars = [make_bar(day) for day in weekdays]

    report = assess_bars_quality(
        bars,
        requested_start=start,
        requested_end=weekdays[-1],
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
    weekdays = weekdays_from(start, 128)
    bars = [make_bar(day) for index, day in enumerate(weekdays) if index >= 8]

    report = assess_bars_quality(
        bars,
        requested_start=start,
        requested_end=weekdays[-1],
        now=date(2026, 5, 10),
    )

    assert report["missing_bar_count"] == 8
    assert report["status"] == "needs_review"
    assert report["severity"] == "medium"


def test_assess_bars_quality_counts_missing_weekdays_distinctly():
    start = date(2026, 1, 1)
    weekdays = weekdays_from(start, 128)
    missing_days = set(weekdays[:8])
    weekend_days = [
        start + timedelta(days=offset)
        for offset in range((weekdays[-1] - start).days + 1)
        if (start + timedelta(days=offset)).weekday() >= 5
    ][:8]
    bars = [make_bar(day) for day in weekdays[8:]]
    bars.extend(make_bar(day) for day in weekend_days)

    report = assess_bars_quality(
        bars,
        requested_start=start,
        requested_end=weekdays[-1],
        now=date(2026, 5, 10),
    )

    assert {day.isoformat() for day in missing_days} == {
        "2026-01-01",
        "2026-01-02",
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-01-12",
    }
    assert report["bar_count"] == 128
    assert report["duplicate_timestamp_count"] == 0
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


def test_build_data_quality_report_counts_raw_invalid_rows_without_raising():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    start = date(2026, 1, 1)

    with session_scope(engine) as session:
        instrument = InstrumentRepository(session).upsert_symbol(
            symbol="000001",
            name="Ping An Bank",
            market=Market.A_STOCK,
            asset_type="stock",
            currency="CNY",
            exchange="SZSE",
        )
        for offset in range(120):
            day = start + timedelta(days=offset)
            high = Decimal("11")
            volume = Decimal("1000")
            if offset == 0:
                high = Decimal("9")
            if offset == 1:
                volume = Decimal("-1")
            session.add(
                MarketBarORM(
                    instrument_id=instrument.id,
                    timestamp=day,
                    timeframe="1d",
                    open=Decimal("10"),
                    high=high,
                    low=Decimal("9"),
                    close=Decimal("10"),
                    volume=volume,
                    adjusted="qfq",
                    source="akshare",
                )
            )

    result = build_data_quality_report(
        engine,
        symbol="000001",
        start=start,
        end=start + timedelta(days=119),
    )

    with session_scope(engine) as session:
        report = DataQualityReportRepository(session).get(result["report_id"])
        assert report is not None
        assert report.status == "failed"
        assert report.severity == "high"
        assert report.invalid_ohlc_count == 1
        assert report.non_positive_volume_count == 1
        assert report.bar_count == 120
