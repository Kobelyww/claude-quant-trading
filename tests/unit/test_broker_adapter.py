from datetime import date
from decimal import Decimal

import pytest

from quant_trading.core.enums import Market, OrderSide, OrderStatus, OrderType
from quant_trading.core.models import Bar, OrderIntent
from quant_trading.execution.broker import (
    BrokerExecutionMode,
    DryRunBrokerAdapter,
    TradingDisabledError,
    broker_order_request_from_intent,
    ensure_trading_enabled,
)


def make_bar() -> Bar:
    return Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=date(2026, 5, 8),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=Decimal("100000"),
    )


def make_intent() -> OrderIntent:
    return OrderIntent(
        instrument_id=1,
        symbol="000001",
        side=OrderSide.BUY,
        quantity=100,
        reason="dry_run_test",
        order_type=OrderType.MARKET,
    )


def test_trading_guard_blocks_live_mode_when_disabled():
    with pytest.raises(TradingDisabledError, match="live trading is disabled"):
        ensure_trading_enabled(False, BrokerExecutionMode.LIVE)

    ensure_trading_enabled(False, BrokerExecutionMode.SIMULATED)
    ensure_trading_enabled(False, BrokerExecutionMode.DRY_RUN)


def test_dry_run_broker_records_request_without_fill():
    bar = make_bar()
    request = broker_order_request_from_intent(make_intent(), bar, "client-1")
    broker = DryRunBrokerAdapter()

    result = broker.submit_order(request, bar)

    assert result.mode is BrokerExecutionMode.DRY_RUN
    assert result.status is OrderStatus.SUBMITTED
    assert result.accepted is True
    assert result.fill is None
    assert result.broker_order_id == "dry-run-client-1"
    assert broker.submitted_requests == [request]


def test_dry_run_broker_cancel_known_and_unknown_order():
    bar = make_bar()
    request = broker_order_request_from_intent(make_intent(), bar, "client-2")
    broker = DryRunBrokerAdapter()
    submitted = broker.submit_order(request, bar)

    cancelled = broker.cancel_order(submitted.broker_order_id)
    missing = broker.cancel_order("dry-run-missing")

    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.accepted is True
    assert missing.status is OrderStatus.REJECTED
    assert missing.accepted is False
