from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from typing import Any

from sqlalchemy import Engine
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_trading.core.models import Bar
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import InstrumentORM, MarketBarORM
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    DataQualityReportRepository,
)

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_NEEDS_REVIEW = "needs_review"
SEVERITY_NONE = "none"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"


def assess_bars_quality(
    bars: list[Bar],
    *,
    requested_start: date | None,
    requested_end: date | None,
    now: date | None = None,
) -> dict[str, Any]:
    current_date = now or datetime.now(UTC).date()
    selected_bars = [
        bar
        for bar in bars
        if (requested_start is None or _bar_date(bar.timestamp) >= requested_start)
        and (requested_end is None or _bar_date(bar.timestamp) <= requested_end)
    ]
    start_date = requested_start or min(
        (_bar_date(bar.timestamp) for bar in selected_bars), default=None
    )
    end_date = requested_end or max(
        (_bar_date(bar.timestamp) for bar in selected_bars), default=None
    )

    bar_count = len(selected_bars)
    expected_weekdays = (
        _weekdays(start_date, end_date)
        if start_date is not None and end_date is not None and start_date <= end_date
        else set()
    )
    expected_bar_count = len(expected_weekdays)
    timestamps = [_bar_date(bar.timestamp) for bar in selected_bars]
    observed_weekdays = {
        timestamp for timestamp in timestamps if timestamp.weekday() < 5
    }
    missing_bar_count = len(expected_weekdays - observed_weekdays)
    duplicate_timestamp_count = sum(
        count - 1 for count in Counter(timestamps).values() if count > 1
    )
    non_positive_price_count = sum(
        1
        for bar in selected_bars
        if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0
    )
    non_positive_volume_count = sum(1 for bar in selected_bars if bar.volume <= 0)
    invalid_ohlc_count = sum(
        1
        for bar in selected_bars
        if bar.high < max(bar.open, bar.close)
        or bar.low > min(bar.open, bar.close)
        or bar.high < bar.low
    )
    stale_data = end_date is not None and (current_date - end_date).days > 10

    findings: list[dict[str, Any]] = []
    if bar_count < 120:
        findings.append(
            {
                "code": "insufficient_bars",
                "severity": SEVERITY_HIGH,
                "message": "Assessed range contains fewer than 120 bars.",
                "count": bar_count,
            }
        )
    if duplicate_timestamp_count > 0:
        findings.append(
            {
                "code": "duplicate_timestamps",
                "severity": SEVERITY_HIGH,
                "message": "Duplicate bar timestamps were found.",
                "count": duplicate_timestamp_count,
            }
        )
    if non_positive_price_count > 0:
        findings.append(
            {
                "code": "non_positive_prices",
                "severity": SEVERITY_HIGH,
                "message": "One or more OHLC prices are non-positive.",
                "count": non_positive_price_count,
            }
        )
    if invalid_ohlc_count > 0:
        findings.append(
            {
                "code": "invalid_ohlc",
                "severity": SEVERITY_HIGH,
                "message": "One or more bars violate OHLC bounds.",
                "count": invalid_ohlc_count,
            }
        )

    missing_ratio = (
        Decimal(missing_bar_count) / Decimal(expected_bar_count)
        if expected_bar_count
        else Decimal("0")
    )
    if missing_ratio > Decimal("0.20"):
        findings.append(
            {
                "code": "missing_coverage",
                "severity": SEVERITY_HIGH,
                "message": "More than 20% of expected weekday bars are missing.",
                "count": missing_bar_count,
                "ratio": str(missing_ratio),
            }
        )
    elif missing_ratio > Decimal("0.05"):
        findings.append(
            {
                "code": "missing_coverage",
                "severity": SEVERITY_MEDIUM,
                "message": "More than 5% of expected weekday bars are missing.",
                "count": missing_bar_count,
                "ratio": str(missing_ratio),
            }
        )
    if stale_data:
        findings.append(
            {
                "code": "stale_data",
                "severity": SEVERITY_MEDIUM,
                "message": "Assessed data ends more than 10 calendar days ago.",
                "end_date": _iso(end_date),
            }
        )

    non_positive_volume_ratio = (
        Decimal(non_positive_volume_count) / Decimal(bar_count)
        if bar_count
        else Decimal("0")
    )
    if non_positive_volume_ratio > Decimal("0.10"):
        findings.append(
            {
                "code": "non_positive_volume",
                "severity": SEVERITY_MEDIUM,
                "message": "More than 10% of bars have non-positive volume.",
                "count": non_positive_volume_count,
                "ratio": str(non_positive_volume_ratio),
            }
        )

    status, severity = _highest_status(findings)
    return {
        "status": status,
        "severity": severity,
        "bar_count": bar_count,
        "expected_bar_count": expected_bar_count,
        "missing_bar_count": missing_bar_count,
        "duplicate_timestamp_count": duplicate_timestamp_count,
        "non_positive_price_count": non_positive_price_count,
        "non_positive_volume_count": non_positive_volume_count,
        "invalid_ohlc_count": invalid_ohlc_count,
        "stale_data": stale_data,
        "data_fingerprint": _fingerprint(selected_bars),
        "findings_payload": {
            "findings": findings,
            "range": {"start": _iso(start_date), "end": _iso(end_date)},
        },
    }


def build_data_quality_report(
    engine: Engine,
    *,
    symbol: str,
    candidate_review_id: int | None = None,
    backtest_run_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    job_run_id: int | None = None,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        report = DataQualityReportRepository(session).create_running(
            candidate_review_id=candidate_review_id,
            backtest_run_id=backtest_run_id,
            job_run_id=job_run_id,
            symbol=symbol,
            source="",
            adjusted="",
            start_date=start,
            end_date=end,
            created_at=started_at,
        )
        report_id = report.id

    try:
        with session_scope(engine) as session:
            reports = DataQualityReportRepository(session)
            report = reports.get(report_id)
            if report is None:
                raise ValueError(f"data quality report {report_id} was not found")
            bars = _list_raw_market_bars(session, symbol, start=start, end=end)
            assessment = assess_bars_quality(
                bars,
                requested_start=start,
                requested_end=end,
            )
            finished_at = datetime.now(UTC).replace(tzinfo=None)
            report = reports.mark_completed(
                report,
                status=assessment["status"],
                severity=assessment["severity"],
                bar_count=assessment["bar_count"],
                expected_bar_count=assessment["expected_bar_count"],
                missing_bar_count=assessment["missing_bar_count"],
                duplicate_timestamp_count=assessment["duplicate_timestamp_count"],
                non_positive_price_count=assessment["non_positive_price_count"],
                non_positive_volume_count=assessment["non_positive_volume_count"],
                invalid_ohlc_count=assessment["invalid_ohlc_count"],
                stale_data=assessment["stale_data"],
                data_fingerprint=assessment["data_fingerprint"],
                findings_payload=json.dumps(
                    assessment["findings_payload"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                finished_at=finished_at,
                duration_ms=_duration_ms(started_at, finished_at),
            )
            if candidate_review_id is not None:
                review = AgentCandidateReviewRepository(session).get(candidate_review_id)
                if review is not None:
                    AgentCandidateReviewRepository(session).link_data_quality_report(
                        review,
                        data_quality_report_id=report.id,
                        updated_at=finished_at,
                    )
            return {
                "report_id": report.id,
                "symbol": report.symbol,
                "status": report.status,
                "severity": report.severity,
                "bar_count": report.bar_count,
                "data_fingerprint": report.data_fingerprint,
            }
    except Exception as exc:
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        with session_scope(engine) as session:
            reports = DataQualityReportRepository(session)
            report = reports.get(report_id)
            if report is not None:
                reports.mark_failed(
                    report,
                    str(exc),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_at, finished_at),
                )
        raise


def _weekday_count(start: date, end: date) -> int:
    return len(_weekdays(start, end))


def _weekdays(start: date, end: date) -> set[date]:
    if end < start:
        return set()
    return {
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    }


def _list_raw_market_bars(
    session: Session,
    symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
    source: str | None = None,
    adjusted: str | None = None,
) -> list[MarketBarORM]:
    statement = (
        select(MarketBarORM)
        .join(InstrumentORM)
        .where(InstrumentORM.symbol == symbol)
        .order_by(MarketBarORM.timestamp)
    )
    if start is not None:
        statement = statement.where(MarketBarORM.timestamp >= start)
    if end is not None:
        statement = statement.where(MarketBarORM.timestamp <= end)
    if source:
        statement = statement.where(MarketBarORM.source == source)
    if adjusted:
        statement = statement.where(MarketBarORM.adjusted == adjusted)
    return list(session.scalars(statement).all())


def _fingerprint(bars: list[Bar]) -> str:
    lines = [
        "|".join(
            [
                _bar_symbol(bar),
                _bar_date(bar.timestamp).isoformat(),
                _decimal_text(bar.open),
                _decimal_text(bar.high),
                _decimal_text(bar.low),
                _decimal_text(bar.close),
                _decimal_text(bar.volume),
                bar.source,
                (
                    bar.adjusted.value
                    if hasattr(bar.adjusted, "value")
                    else str(bar.adjusted)
                ),
            ]
        )
        for bar in bars
    ]
    payload = "\n".join(sorted(lines))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _highest_status(findings: list[dict[str, Any]]) -> tuple[str, str]:
    severities = {finding["severity"] for finding in findings}
    if SEVERITY_HIGH in severities:
        return STATUS_FAILED, SEVERITY_HIGH
    if SEVERITY_MEDIUM in severities:
        return STATUS_NEEDS_REVIEW, SEVERITY_MEDIUM
    return STATUS_PASSED, SEVERITY_NONE


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _bar_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _bar_symbol(bar: Any) -> str:
    symbol = getattr(bar, "symbol", None)
    if symbol is not None:
        return str(symbol)
    instrument = getattr(bar, "instrument", None)
    if instrument is not None:
        return str(instrument.symbol)
    return ""


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return int((finished_at - started_at).total_seconds() * 1000)
