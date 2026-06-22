from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import (
    CashLedgerORM,
    PaperAccountORM,
    PaperFillORM,
    PaperOrderORM,
    PaperPositionORM,
    PaperRunORM,
    PortfolioSnapshotORM,
    RiskDecisionORM,
)

router = APIRouter()


def _float(value: Decimal | int | float | None) -> float | None:
    return None if value is None else float(value)


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _account_payload(row: PaperAccountORM) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "base_currency": row.base_currency,
        "initial_cash": float(row.initial_cash),
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def _run_payload(row: PaperRunORM) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "strategy_name": row.strategy_name,
        "symbol": row.symbol,
        "universe_config": row.universe_config,
        "strategy_config": row.strategy_config,
        "risk_config": row.risk_config,
        "status": row.status,
        "last_processed_at": _iso(row.last_processed_at),
        "started_at": _iso(row.started_at),
        "stopped_at": _iso(row.stopped_at),
        "created_at": row.created_at.isoformat(),
    }


def _position_payload(row: PaperPositionORM) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "instrument_id": row.instrument_id,
        "symbol": row.symbol,
        "quantity": row.quantity,
        "avg_cost": float(row.avg_cost),
        "market_price": float(row.market_price),
        "realized_pnl": float(row.realized_pnl),
        "updated_at": row.updated_at.isoformat(),
    }


def _cash_ledger_payload(row: CashLedgerORM) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "run_id": row.run_id,
        "order_id": row.order_id,
        "fill_id": row.fill_id,
        "event_type": row.event_type,
        "amount": float(row.amount),
        "cash_after": float(row.cash_after),
        "currency": row.currency,
        "occurred_at": row.occurred_at.isoformat(),
        "created_at": row.created_at.isoformat(),
    }


def _order_payload(row: PaperOrderORM) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "account_id": row.account_id,
        "instrument_id": row.instrument_id,
        "symbol": row.symbol,
        "side": row.side,
        "order_type": row.order_type,
        "quantity": row.quantity,
        "limit_price": _float(row.limit_price),
        "reason": row.reason,
        "status": row.status,
        "risk_decision": row.risk_decision,
        "submitted_at": row.submitted_at.isoformat(),
        "created_at": row.created_at.isoformat(),
    }


def _fill_payload(row: PaperFillORM) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "account_id": row.account_id,
        "order_id": row.order_id,
        "instrument_id": row.instrument_id,
        "symbol": row.symbol,
        "side": row.side,
        "quantity": row.quantity,
        "price": float(row.price),
        "commission": float(row.commission),
        "slippage": float(row.slippage),
        "filled_at": row.filled_at.isoformat(),
        "created_at": row.created_at.isoformat(),
    }


def _risk_decision_payload(row: RiskDecisionORM) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "order_id": row.order_id,
        "decision": row.decision,
        "rule_name": row.rule_name,
        "message": row.message,
        "created_at": row.created_at.isoformat(),
    }


def _snapshot_payload(row: PortfolioSnapshotORM) -> dict:
    return {
        "account_id": row.account_id,
        "timestamp": row.timestamp.isoformat(),
        "equity": float(row.equity),
        "cash": float(row.cash),
        "market_value": float(row.market_value),
        "drawdown": float(row.drawdown),
    }


def _get_account_or_404(session, account_id: int) -> PaperAccountORM:
    account = session.get(PaperAccountORM, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="paper account not found")
    return account


def _get_run_or_404(session, run_id: int) -> PaperRunORM:
    run = session.get(PaperRunORM, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="paper run not found")
    return run


@router.get("/paper/accounts")
def list_paper_accounts(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = session.scalars(
            select(PaperAccountORM).order_by(PaperAccountORM.id)
        ).all()
        return [_account_payload(row) for row in rows]


@router.get("/paper/accounts/{account_id}")
def get_paper_account(account_id: int, request: Request) -> dict:
    with session_scope(request.app.state.engine) as session:
        return _account_payload(_get_account_or_404(session, account_id))


@router.get("/paper/accounts/{account_id}/positions")
def list_paper_account_positions(account_id: int, request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        _get_account_or_404(session, account_id)
        rows = session.scalars(
            select(PaperPositionORM)
            .where(PaperPositionORM.account_id == account_id)
            .order_by(PaperPositionORM.symbol)
        ).all()
        return [_position_payload(row) for row in rows]


@router.get("/paper/accounts/{account_id}/cash-ledger")
def list_paper_account_cash_ledger(account_id: int, request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        _get_account_or_404(session, account_id)
        rows = session.scalars(
            select(CashLedgerORM)
            .where(CashLedgerORM.account_id == account_id)
            .order_by(CashLedgerORM.id)
        ).all()
        return [_cash_ledger_payload(row) for row in rows]


@router.get("/paper/runs")
def list_paper_runs(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = session.scalars(select(PaperRunORM).order_by(PaperRunORM.id)).all()
        return [_run_payload(row) for row in rows]


@router.get("/paper/runs/{run_id}")
def get_paper_run(run_id: int, request: Request) -> dict:
    with session_scope(request.app.state.engine) as session:
        return _run_payload(_get_run_or_404(session, run_id))


@router.get("/paper/runs/{run_id}/orders")
def list_paper_run_orders(run_id: int, request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        _get_run_or_404(session, run_id)
        rows = session.scalars(
            select(PaperOrderORM)
            .where(PaperOrderORM.run_id == run_id)
            .order_by(PaperOrderORM.id)
        ).all()
        return [_order_payload(row) for row in rows]


@router.get("/paper/runs/{run_id}/fills")
def list_paper_run_fills(run_id: int, request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        _get_run_or_404(session, run_id)
        rows = session.scalars(
            select(PaperFillORM)
            .where(PaperFillORM.run_id == run_id)
            .order_by(PaperFillORM.id)
        ).all()
        return [_fill_payload(row) for row in rows]


@router.get("/paper/runs/{run_id}/risk-decisions")
def list_paper_run_risk_decisions(run_id: int, request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        _get_run_or_404(session, run_id)
        rows = session.scalars(
            select(RiskDecisionORM)
            .where(RiskDecisionORM.run_id == run_id)
            .order_by(RiskDecisionORM.id)
        ).all()
        return [_risk_decision_payload(row) for row in rows]


@router.get("/paper/runs/{run_id}/snapshots")
def list_paper_run_snapshots(run_id: int, request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        run = _get_run_or_404(session, run_id)
        rows = session.scalars(
            select(PortfolioSnapshotORM)
            .where(PortfolioSnapshotORM.account_id == run.account_id)
            .order_by(PortfolioSnapshotORM.timestamp.desc())
        ).all()
        return [_snapshot_payload(row) for row in rows]


@router.get("/paper/snapshots")
def list_paper_snapshots(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = session.scalars(
            select(PortfolioSnapshotORM).order_by(PortfolioSnapshotORM.timestamp.desc())
        ).all()
        return [_snapshot_payload(row) for row in rows]
