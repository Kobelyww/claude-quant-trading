from fastapi import APIRouter, Request
from sqlalchemy import select

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import InstrumentORM

router = APIRouter()


@router.get("/instruments")
def list_instruments(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = session.scalars(
            select(InstrumentORM).order_by(InstrumentORM.symbol)
        ).all()
        return [
            {
                "id": row.id,
                "symbol": row.symbol,
                "name": row.name,
                "market": row.market,
                "asset_type": row.asset_type,
                "currency": row.currency,
                "exchange": row.exchange,
                "status": row.status,
            }
            for row in rows
        ]
