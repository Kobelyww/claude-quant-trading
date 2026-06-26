from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    BacktestEquityPointORM,
    BacktestFillORM,
    BacktestOrderORM,
    BacktestRunORM,
)
from quant_trading.validation.metrics import (
    buy_and_hold_benchmark,
    cap_readiness,
    metric_payload_from_run,
)


def test_cap_readiness_never_exceeds_floor():
    assert cap_readiness("ready_for_paper_research", "not_ready") == ("not_ready", True)
    assert cap_readiness("ready_for_paper_research", "needs_review") == (
        "needs_review",
        True,
    )
    assert cap_readiness("needs_review", "ready_for_paper_research") == (
        "needs_review",
        False,
    )
    assert cap_readiness("not_ready", "ready_for_paper_research") == (
        "not_ready",
        False,
    )


def test_backtest_metric_payload_handles_empty_orders():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    with session_scope(engine) as session:
        run = BacktestRunORM(
            strategy_name="ma_cross",
            symbol="000001",
            initial_cash=Decimal("100000"),
            final_equity=Decimal("101500"),
            status="done",
        )
        session.add(run)
        session.flush()
        session.add_all(
            [
                BacktestEquityPointORM(
                    run_id=run.id,
                    timestamp=date(2026, 1, 1),
                    equity=Decimal("100000"),
                    cash=Decimal("100000"),
                    market_value=Decimal("0"),
                    drawdown=Decimal("0"),
                ),
                BacktestEquityPointORM(
                    run_id=run.id,
                    timestamp=date(2026, 1, 2),
                    equity=Decimal("101500"),
                    cash=Decimal("101500"),
                    market_value=Decimal("0"),
                    drawdown=Decimal("0.02"),
                ),
            ]
        )
        session.flush()

        payload = metric_payload_from_run(session, run)

    assert payload == {
        "backtest_run_id": run.id,
        "symbol": "000001",
        "strategy_name": "ma_cross",
        "status": "done",
        "initial_cash": "100000.000000",
        "final_equity": "101500.000000",
        "absolute_pnl": "1500.000000",
        "return_pct": "1.500000",
        "equity_point_count": 2,
        "order_count": 0,
        "fill_count": 0,
        "max_drawdown": "0.020000",
    }


def test_buy_and_hold_benchmark_returns_metrics_without_persisting_orders():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    bars = [
        Bar(
            instrument_id=1,
            symbol="000001",
            market=Market.A_STOCK,
            timestamp=date(2026, 1, 1),
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10"),
            volume=Decimal("1000"),
        ),
        Bar(
            instrument_id=1,
            symbol="000001",
            market=Market.A_STOCK,
            timestamp=date(2026, 1, 2),
            open=Decimal("12"),
            high=Decimal("13"),
            low=Decimal("11"),
            close=Decimal("12"),
            volume=Decimal("1000"),
        ),
    ]

    metrics = buy_and_hold_benchmark(
        bars,
        initial_cash=Decimal("100000"),
        commission_rate=Decimal("0.0003"),
        slippage_rate=Decimal("0.001"),
    )

    with session_scope(engine) as session:
        order_count = session.scalar(select(func.count(BacktestOrderORM.id)))
        fill_count = session.scalar(select(func.count(BacktestFillORM.id)))

    assert metrics["bar_count"] == 2
    assert metrics["start"] == "2026-01-01"
    assert metrics["end"] == "2026-01-02"
    assert metrics["initial_cash"] == "100000.000000"
    assert metrics["final_equity"] == "119688.377792"
    assert metrics["absolute_pnl"] == "19688.377792"
    assert metrics["return_pct"] == "19.688378"
    assert metrics["order_count"] == 0
    assert metrics["fill_count"] == 0
    assert order_count == 0
    assert fill_count == 0

    zero_cash_metrics = buy_and_hold_benchmark(
        bars,
        initial_cash=Decimal("0"),
        commission_rate=Decimal("0.0003"),
        slippage_rate=Decimal("0.001"),
    )
    assert zero_cash_metrics["final_equity"] == "0.000000"
    assert zero_cash_metrics["absolute_pnl"] == "0.000000"
    assert zero_cash_metrics["return_pct"] == "0.000000"


def test_buy_and_hold_benchmark_preserves_cash_when_no_bars():
    metrics = buy_and_hold_benchmark(
        [],
        initial_cash=Decimal("100000"),
        commission_rate=Decimal("0.0003"),
        slippage_rate=Decimal("0.001"),
    )

    assert metrics["bar_count"] == 0
    assert metrics["final_equity"] == "100000.000000"
    assert metrics["absolute_pnl"] == "0.000000"
    assert metrics["return_pct"] == "0.000000"


def test_buy_and_hold_benchmark_flat_prices_reflects_costs():
    bars = [
        Bar(
            instrument_id=1,
            symbol="000001",
            market=Market.A_STOCK,
            timestamp=date(2026, 1, 1),
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("10"),
            close=Decimal("10"),
            volume=Decimal("1000"),
        ),
        Bar(
            instrument_id=1,
            symbol="000001",
            market=Market.A_STOCK,
            timestamp=date(2026, 1, 2),
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("10"),
            close=Decimal("10"),
            volume=Decimal("1000"),
        ),
    ]

    metrics = buy_and_hold_benchmark(
        bars,
        initial_cash=Decimal("100000"),
        commission_rate=Decimal("0.0003"),
        slippage_rate=Decimal("0.001"),
    )

    assert metrics["final_equity"] == "99740.338000"
    assert metrics["absolute_pnl"] == "-259.662000"
    assert metrics["return_pct"] == "-0.259662"
    assert metrics["max_drawdown"] == "0.000000"
