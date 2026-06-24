from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import AgentRunORM
from quant_trading.storage.repositories import AgentRunRepository

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


@router.get("")
def list_agent_runs(
    request: Request,
    agent_type: str | None = None,
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = AgentRunRepository(session).list_recent(
            agent_type=agent_type,
            status=status,
            symbol=symbol,
            limit=limit,
        )
        return [_agent_run_payload(row) for row in rows]


@router.get("/{agent_run_id}")
def get_agent_run(agent_run_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = AgentRunRepository(session).get(agent_run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        return _agent_run_payload(row)


def _agent_run_payload(row: AgentRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent_type": row.agent_type,
        "status": row.status,
        "symbol": row.symbol,
        "model_name": row.model_name,
        "request_payload": _json_loads(row.request_payload),
        "metrics_payload": _json_loads(row.metrics_payload),
        "result_payload": _json_loads(row.result_payload),
        "error_message": row.error_message,
        "job_run_id": row.job_run_id,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
        "created_at": _iso(row.created_at),
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
