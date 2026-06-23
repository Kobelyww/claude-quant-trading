from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Engine

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import WorkflowRunORM
from quant_trading.storage.repositories import WorkflowRunRepository
from quant_trading.workflows.operations import (
    create_paper_account,
    import_legacy_data,
    run_ma_cross_backtest,
    run_paper_tick,
    start_ma_cross_paper_run,
)
from quant_trading.workflows.runner import WorkflowCommandRunner

router = APIRouter(prefix="/workflows", tags=["workflows"])
T = TypeVar("T")


class ImportLegacyRequest(BaseModel):
    legacy_db_path: str = Field(min_length=1)


class MACrossBacktestRequest(BaseModel):
    symbol: str = Field(min_length=1)
    short_window: int = Field(gt=0)
    long_window: int = Field(gt=0)
    order_size: int = Field(gt=0)
    initial_cash: Decimal = Field(gt=Decimal("0"))

    @model_validator(mode="after")
    def validate_windows(self) -> "MACrossBacktestRequest":
        if self.long_window <= self.short_window:
            raise ValueError("long_window must be greater than short_window")
        return self


class CreatePaperAccountRequest(BaseModel):
    name: str = Field(min_length=1)
    initial_cash: Decimal = Field(gt=Decimal("0"))
    base_currency: str = "CNY"

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("paper account name is required")
        return value

    @field_validator("base_currency")
    @classmethod
    def normalize_base_currency(cls, value: str) -> str:
        value = value.strip() if value else "CNY"
        return value or "CNY"


class CreateMACrossPaperRunRequest(BaseModel):
    account_id: int = Field(gt=0)
    symbol: str = Field(min_length=1)
    short_window: int = Field(gt=0)
    long_window: int = Field(gt=0)
    order_size: int = Field(gt=0)
    max_order_value: Decimal = Field(default=Decimal("100000"), gt=Decimal("0"))

    @model_validator(mode="after")
    def validate_windows(self) -> "CreateMACrossPaperRunRequest":
        if self.long_window <= self.short_window:
            raise ValueError("long_window must be greater than short_window")
        return self


def _run_command(callback: Callable[[], T]) -> T:
    try:
        return callback()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


def _engine(request: Request) -> Engine:
    return request.app.state.engine


def _runner(request: Request) -> WorkflowCommandRunner:
    return WorkflowCommandRunner(_engine(request))


def _workflow_run_payload(row: WorkflowRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "command_name": row.command_name,
        "status": row.status,
        "request_payload": _json_loads(row.request_payload),
        "result_payload": _json_loads(row.result_payload),
        "error_message": row.error_message,
        "created_object_type": row.created_object_type,
        "created_object_id": row.created_object_id,
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


@router.post("/import-legacy")
def import_legacy(payload: ImportLegacyRequest, request: Request) -> dict:
    return _run_command(
        lambda: _runner(request).run(
            "import_legacy",
            payload.model_dump(mode="json"),
            lambda: import_legacy_data(
                _engine(request),
                payload.legacy_db_path,
            ),
        )
    )


@router.post("/backtests/ma-cross")
def run_backtest(payload: MACrossBacktestRequest, request: Request) -> dict:
    return _run_command(
        lambda: _runner(request).run(
            "backtest_ma_cross",
            payload.model_dump(mode="json"),
            lambda: run_ma_cross_backtest(
                _engine(request),
                symbol=payload.symbol,
                short_window=payload.short_window,
                long_window=payload.long_window,
                order_size=payload.order_size,
                initial_cash=payload.initial_cash,
            ),
        )
    )


@router.post("/paper/accounts")
def create_account(payload: CreatePaperAccountRequest, request: Request) -> dict:
    return _run_command(
        lambda: _runner(request).run(
            "paper_create_account",
            payload.model_dump(mode="json"),
            lambda: create_paper_account(
                _engine(request),
                name=payload.name,
                initial_cash=payload.initial_cash,
                base_currency=payload.base_currency,
            ),
        )
    )


@router.post("/paper/runs/ma-cross")
def start_paper_run(payload: CreateMACrossPaperRunRequest, request: Request) -> dict:
    return _run_command(
        lambda: _runner(request).run(
            "paper_start_ma_cross_run",
            payload.model_dump(mode="json"),
            lambda: start_ma_cross_paper_run(
                _engine(request),
                account_id=payload.account_id,
                symbol=payload.symbol,
                short_window=payload.short_window,
                long_window=payload.long_window,
                order_size=payload.order_size,
                max_order_value=payload.max_order_value,
            ),
        )
    )


@router.post("/paper/runs/{run_id}/tick")
def run_tick(run_id: int, request: Request) -> dict:
    return _run_command(
        lambda: _runner(request).run(
            "paper_run_tick",
            {"run_id": run_id},
            lambda: run_paper_tick(_engine(request), run_id),
        )
    )


@router.get("/runs")
def list_workflow_runs(
    request: Request,
    status: str | None = None,
    command_name: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(_engine(request)) as session:
        rows = WorkflowRunRepository(session).list_recent(
            status=status,
            command_name=command_name,
            limit=limit,
        )
        return [_workflow_run_payload(row) for row in rows]


@router.get("/runs/{workflow_run_id}")
def get_workflow_run(workflow_run_id: int, request: Request) -> dict[str, Any]:
    with session_scope(_engine(request)) as session:
        row = WorkflowRunRepository(session).get(workflow_run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        return _workflow_run_payload(row)
