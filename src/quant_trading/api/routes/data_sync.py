from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import DataSyncRunORM
from quant_trading.storage.repositories import DataSyncRunRepository

router = APIRouter(prefix="/data-sync-runs", tags=["data-sync"])


@router.get("")
def list_data_sync_runs(
    request: Request,
    provider: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = DataSyncRunRepository(session).list_recent(
            provider=provider,
            symbol=symbol,
            status=status,
            limit=limit,
        )
        return [_data_sync_run_payload(row) for row in rows]


@router.get("/{sync_run_id}")
def get_data_sync_run(sync_run_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = DataSyncRunRepository(session).get(sync_run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="data sync run not found")
        return _data_sync_run_payload(row)


def _data_sync_run_payload(row: DataSyncRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "symbol": row.symbol,
        "market": row.market,
        "asset_type": row.asset_type,
        "currency": row.currency,
        "exchange": row.exchange,
        "start_date": _iso(row.start_date),
        "end_date": _iso(row.end_date),
        "status": row.status,
        "imported_bars": row.imported_bars,
        "job_run_id": row.job_run_id,
        "error_message": row.error_message,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
        "created_at": _iso(row.created_at),
    }


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
