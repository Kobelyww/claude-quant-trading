from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import ResearchValidationReportORM
from quant_trading.storage.repositories import ResearchValidationReportRepository

router = APIRouter(
    prefix="/research-validation-reports",
    tags=["research-validation-reports"],
)


@router.get("")
def list_research_validation_reports(
    request: Request,
    candidate_review_id: int | None = None,
    symbol: str | None = None,
    validation_status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = ResearchValidationReportRepository(session).list_recent(
            candidate_review_id=candidate_review_id,
            symbol=symbol,
            validation_status=validation_status,
            limit=limit,
        )
        return [_research_validation_report_payload(row) for row in rows]


@router.get("/{report_id}")
def get_research_validation_report(report_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = ResearchValidationReportRepository(session).get(report_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail="research validation report not found",
            )
        return _research_validation_report_payload(row)


def _research_validation_report_payload(row: ResearchValidationReportORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "candidate_review_id": row.candidate_review_id,
        "source_backtest_run_id": row.source_backtest_run_id,
        "data_quality_report_id": row.data_quality_report_id,
        "job_run_id": row.job_run_id,
        "symbol": row.symbol,
        "strategy_name": row.strategy_name,
        "validation_status": row.validation_status,
        "readiness_floor": row.readiness_floor,
        "in_sample_metrics_payload": _json_loads(row.in_sample_metrics_payload),
        "out_of_sample_metrics_payload": _json_loads(row.out_of_sample_metrics_payload),
        "walk_forward_payload": _json_loads(row.walk_forward_payload),
        "parameter_sensitivity_payload": _json_loads(
            row.parameter_sensitivity_payload
        ),
        "benchmark_payload": _json_loads(row.benchmark_payload),
        "summary_payload": _json_loads(row.summary_payload),
        "error_message": row.error_message,
        "created_at": _iso(row.created_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
