from fastapi import APIRouter, Request
from sqlalchemy import select

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import PortfolioSnapshotORM

router = APIRouter()


@router.get("/paper/snapshots")
def list_paper_snapshots(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = session.scalars(
            select(PortfolioSnapshotORM).order_by(PortfolioSnapshotORM.timestamp.desc())
        ).all()
        return [
            {
                "account_id": row.account_id,
                "timestamp": row.timestamp.isoformat(),
                "equity": float(row.equity),
                "cash": float(row.cash),
                "market_value": float(row.market_value),
                "drawdown": float(row.drawdown),
            }
            for row in rows
        ]
