from copy import deepcopy
from decimal import Decimal

from quant_trading.core.enums import OrderSide
from quant_trading.core.models import Fill, Portfolio, Position


def apply_fill(portfolio: Portfolio, fill: Fill) -> Portfolio:
    updated = deepcopy(portfolio)
    notional = fill.price * Decimal(fill.quantity)

    if fill.side is OrderSide.BUY:
        total_cost = notional + fill.commission
        if total_cost > updated.cash:
            raise ValueError("insufficient cash for buy fill")
        updated.cash -= total_cost
        existing = updated.positions.get(fill.instrument_id)
        if existing:
            total_quantity = existing.quantity + fill.quantity
            total_cost = existing.avg_cost * Decimal(existing.quantity) + total_cost
            existing.quantity = total_quantity
            existing.avg_cost = total_cost / Decimal(total_quantity)
            existing.market_price = fill.price
        else:
            updated.positions[fill.instrument_id] = Position(
                instrument_id=fill.instrument_id,
                symbol=fill.symbol,
                quantity=fill.quantity,
                avg_cost=total_cost / Decimal(fill.quantity),
                market_price=fill.price,
            )
    else:
        existing = updated.positions.get(fill.instrument_id)
        if not existing or existing.quantity < fill.quantity:
            raise ValueError("cannot sell more shares than the portfolio holds")
        realized = (fill.price - existing.avg_cost) * Decimal(fill.quantity) - fill.commission
        updated.cash += notional - fill.commission
        updated.realized_pnl += realized
        existing.quantity -= fill.quantity
        existing.market_price = fill.price
        if existing.quantity == 0:
            del updated.positions[fill.instrument_id]

    updated.peak_equity = max(updated.peak_equity or updated.equity, updated.equity)
    return updated
