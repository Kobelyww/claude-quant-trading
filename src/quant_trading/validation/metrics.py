from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_trading.core.models import Bar
from quant_trading.storage.models import (
    BacktestEquityPointORM,
    BacktestFillORM,
    BacktestOrderORM,
    BacktestRunORM,
)


READINESS_ORDER = {
    "not_ready": 0,
    "needs_review": 1,
    "ready_for_paper_research": 2,
}


def cap_readiness(value: str, floor: str) -> tuple[str, bool]:
    value_rank = READINESS_ORDER.get(value, READINESS_ORDER["needs_review"])
    floor_rank = READINESS_ORDER.get(floor, READINESS_ORDER["not_ready"])
    if value_rank > floor_rank:
        capped = next(key for key, rank in READINESS_ORDER.items() if rank == floor_rank)
        return capped, True
    return value if value in READINESS_ORDER else "needs_review", False


def decimal_string(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def metric_payload_from_run(session: Session, run: BacktestRunORM) -> dict[str, Any]:
    initial_cash = _decimal(run.initial_cash)
    final_equity = _decimal(run.final_equity)
    absolute_pnl = final_equity - initial_cash
    return_pct = _return_pct(absolute_pnl, initial_cash)

    equity_point_count = session.scalar(
        select(func.count(BacktestEquityPointORM.id)).where(
            BacktestEquityPointORM.run_id == run.id
        )
    )
    max_drawdown = session.scalar(
        select(func.max(BacktestEquityPointORM.drawdown)).where(
            BacktestEquityPointORM.run_id == run.id
        )
    )
    order_count = session.scalar(
        select(func.count(BacktestOrderORM.id)).where(BacktestOrderORM.run_id == run.id)
    )
    fill_count = session.scalar(
        select(func.count(BacktestFillORM.id)).where(BacktestFillORM.run_id == run.id)
    )

    return {
        "backtest_run_id": run.id,
        "symbol": run.symbol,
        "strategy_name": run.strategy_name,
        "status": run.status,
        "initial_cash": decimal_string(initial_cash),
        "final_equity": decimal_string(final_equity),
        "absolute_pnl": decimal_string(absolute_pnl),
        "return_pct": decimal_string(return_pct),
        "equity_point_count": int(equity_point_count or 0),
        "order_count": int(order_count or 0),
        "fill_count": int(fill_count or 0),
        "max_drawdown": decimal_string(_decimal(max_drawdown or 0)),
    }


def buy_and_hold_benchmark(
    bars: list[Bar],
    *,
    initial_cash: Decimal,
    commission_rate: Decimal,
    slippage_rate: Decimal,
) -> dict[str, Any]:
    if not bars or initial_cash <= Decimal("0"):
        return _zero_benchmark_payload(bars, initial_cash=initial_cash)

    entry_price = bars[0].close * (Decimal("1") + slippage_rate)
    if entry_price <= Decimal("0"):
        return _benchmark_payload(
            bars,
            initial_cash=initial_cash,
            final_equity=initial_cash,
            max_drawdown=Decimal("0"),
        )

    budget_per_share = entry_price * (Decimal("1") + commission_rate)
    quantity = (initial_cash / budget_per_share).to_integral_value(rounding=ROUND_FLOOR)
    deployed_cash = quantity * budget_per_share
    remaining_cash = initial_cash - deployed_cash

    equity_values = [
        remaining_cash + (quantity * bar.close)
        for bar in bars
    ]
    exit_price = bars[-1].close * (Decimal("1") - slippage_rate)
    exit_proceeds = quantity * exit_price * (Decimal("1") - commission_rate)
    final_equity = remaining_cash + exit_proceeds
    max_drawdown = _max_drawdown(equity_values)
    return _benchmark_payload(
        bars,
        initial_cash=initial_cash,
        final_equity=final_equity,
        max_drawdown=max_drawdown,
    )


def _benchmark_payload(
    bars: list[Bar],
    *,
    initial_cash: Decimal,
    final_equity: Decimal,
    max_drawdown: Decimal,
) -> dict[str, Any]:
    absolute_pnl = final_equity - initial_cash
    return {
        "bar_count": len(bars),
        "start": _isoformat(bars[0].timestamp) if bars else None,
        "end": _isoformat(bars[-1].timestamp) if bars else None,
        "initial_cash": decimal_string(_decimal(initial_cash)),
        "final_equity": decimal_string(_decimal(final_equity)),
        "absolute_pnl": decimal_string(_decimal(absolute_pnl)),
        "return_pct": decimal_string(_return_pct(absolute_pnl, initial_cash)),
        "max_drawdown": decimal_string(_decimal(max_drawdown)),
        "order_count": 0,
        "fill_count": 0,
    }


def _zero_benchmark_payload(bars: list[Bar], *, initial_cash: Decimal) -> dict[str, Any]:
    return {
        "bar_count": len(bars),
        "start": _isoformat(bars[0].timestamp) if bars else None,
        "end": _isoformat(bars[-1].timestamp) if bars else None,
        "initial_cash": decimal_string(_decimal(initial_cash)),
        "final_equity": "0.000000",
        "absolute_pnl": "0.000000",
        "return_pct": "0.000000",
        "max_drawdown": "0.000000",
        "order_count": 0,
        "fill_count": 0,
    }


def _max_drawdown(equity_values: list[Decimal]) -> Decimal:
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for equity in equity_values:
        if equity > peak:
            peak = equity
        if peak <= Decimal("0"):
            continue
        drawdown = (peak - equity) / peak
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def _return_pct(absolute_pnl: Decimal, initial_cash: Decimal) -> Decimal:
    if initial_cash == Decimal("0"):
        return Decimal("0")
    return (absolute_pnl / initial_cash) * Decimal("100")


def _decimal(value: Any) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _isoformat(value: date | datetime | str) -> str:
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
