from collections.abc import Callable
from decimal import Decimal
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Engine

from quant_trading.workflows.operations import (
    create_paper_account,
    import_legacy_data,
    run_ma_cross_backtest,
    run_paper_tick,
    start_ma_cross_paper_run,
)

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


@router.post("/import-legacy")
def import_legacy(payload: ImportLegacyRequest, request: Request) -> dict:
    return _run_command(
        lambda: import_legacy_data(
            _engine(request),
            payload.legacy_db_path,
        )
    )


@router.post("/backtests/ma-cross")
def run_backtest(payload: MACrossBacktestRequest, request: Request) -> dict:
    return _run_command(
        lambda: run_ma_cross_backtest(
            _engine(request),
            symbol=payload.symbol,
            short_window=payload.short_window,
            long_window=payload.long_window,
            order_size=payload.order_size,
            initial_cash=payload.initial_cash,
        )
    )


@router.post("/paper/accounts")
def create_account(payload: CreatePaperAccountRequest, request: Request) -> dict:
    return _run_command(
        lambda: create_paper_account(
            _engine(request),
            name=payload.name,
            initial_cash=payload.initial_cash,
            base_currency=payload.base_currency,
        )
    )


@router.post("/paper/runs/ma-cross")
def start_paper_run(payload: CreateMACrossPaperRunRequest, request: Request) -> dict:
    return _run_command(
        lambda: start_ma_cross_paper_run(
            _engine(request),
            account_id=payload.account_id,
            symbol=payload.symbol,
            short_window=payload.short_window,
            long_window=payload.long_window,
            order_size=payload.order_size,
            max_order_value=payload.max_order_value,
        )
    )


@router.post("/paper/runs/{run_id}/tick")
def run_tick(run_id: int, request: Request) -> dict:
    return _run_command(lambda: run_paper_tick(_engine(request), run_id))
