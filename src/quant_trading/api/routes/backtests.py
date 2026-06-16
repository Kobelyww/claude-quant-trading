from fastapi import APIRouter, Request
from sqlalchemy import select

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import BacktestRunORM

router = APIRouter()


@router.get("/backtests")
def list_backtests(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = session.scalars(
            select(BacktestRunORM).order_by(BacktestRunORM.id.desc())
        ).all()
        return [
            {
                "id": row.id,
                "symbol": row.symbol,
                "strategy_name": row.strategy_name,
                "initial_cash": float(row.initial_cash),
                "final_equity": float(row.final_equity),
                "status": row.status,
            }
            for row in rows
        ]
