from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import DataQualityReportORM
from quant_trading.storage.repositories import DataQualityReportRepository

router = APIRouter(prefix="/data-quality-reports", tags=["data-quality-reports"])


@router.get("")
def list_data_quality_reports(
    request: Request,
    symbol: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    candidate_review_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = DataQualityReportRepository(session).list_recent(
            candidate_review_id=candidate_review_id,
            symbol=symbol,
            status=status,
            severity=severity,
            limit=limit,
        )
        return [_data_quality_report_payload(row) for row in rows]


@router.get("/{report_id}")
def get_data_quality_report(report_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = DataQualityReportRepository(session).get(report_id)
        if row is None:
            raise HTTPException(status_code=404, detail="data quality report not found")
        return _data_quality_report_payload(row)


def _data_quality_report_payload(row: DataQualityReportORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "candidate_review_id": row.candidate_review_id,
        "backtest_run_id": row.backtest_run_id,
        "job_run_id": row.job_run_id,
        "symbol": row.symbol,
        "source": row.source,
        "adjusted": row.adjusted,
        "start_date": _iso(row.start_date),
        "end_date": _iso(row.end_date),
        "bar_count": row.bar_count,
        "expected_bar_count": row.expected_bar_count,
        "missing_bar_count": row.missing_bar_count,
        "duplicate_timestamp_count": row.duplicate_timestamp_count,
        "non_positive_price_count": row.non_positive_price_count,
        "non_positive_volume_count": row.non_positive_volume_count,
        "invalid_ohlc_count": row.invalid_ohlc_count,
        "stale_data": row.stale_data,
        "data_fingerprint": row.data_fingerprint,
        "status": row.status,
        "severity": row.severity,
        "findings_payload": _json_loads(row.findings_payload),
        "error_message": row.error_message,
        "created_at": _iso(row.created_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
