from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from quant_trading.core.enums import Market, OrderSide, OrderType
from quant_trading.core.models import Bar
from quant_trading.operations import (
    ExecutionOrderStateMachine,
    PreLiveRiskProfile,
    PreLiveSafetyService,
    SafetyPolicyInput,
)


def _policy_input(**overrides) -> SafetyPolicyInput:
    now = date(2026, 6, 26)
    latest_bar = Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=now,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=Decimal("100000"),
    )
    payload = {
        "client_order_id": "order-1",
        "symbol": "000001",
        "instrument_id": 1,
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": 100,
        "limit_price": None,
        "estimated_price": Decimal("10"),
        "broker_mode": "simulated",
        "latest_bar": latest_bar,
        "as_of": now,
        "cash": Decimal("1000000"),
        "market_value": Decimal("0"),
        "peak_equity": Decimal("1000000"),
        "daily_turnover": Decimal("0"),
        "daily_order_count": 0,
        "position_quantity": 100,
        "kill_switch_active": False,
        "dry_run_enabled": True,
        "simulated_enabled": True,
        "live_enabled": False,
    }
    payload.update(overrides)
    return SafetyPolicyInput(**payload)


def test_default_pre_live_risk_profile_matches_policy_spec():
    profile = PreLiveRiskProfile.default()

    assert profile.name == "pre_live_default"
    assert profile.max_single_order_notional == Decimal("100000")
    assert profile.max_gross_exposure_ratio == Decimal("1.0")
    assert profile.max_daily_turnover == Decimal("300000")
    assert profile.max_daily_order_count == 20
    assert profile.max_drawdown_stop_ratio == Decimal("0.10")
    assert profile.stale_data_max_age_days == 10
    assert profile.manual_approval_notional == Decimal("50000")
    assert profile.manual_approval_sell_without_position is True
    assert profile.allowed_broker_modes == {"simulated", "dry_run"}


def test_execution_order_state_machine_allows_only_specified_transitions():
    allowed = [
        ("created", "risk_approved"),
        ("created", "approval_required"),
        ("created", "blocked"),
        ("created", "cancelled"),
        ("approval_required", "operator_approved"),
        ("approval_required", "blocked"),
        ("approval_required", "cancelled"),
        ("risk_approved", "submitted"),
        ("risk_approved", "skipped"),
        ("risk_approved", "cancelled"),
        ("operator_approved", "submitted"),
        ("operator_approved", "skipped"),
    ]
    for current, next_status in allowed:
        ExecutionOrderStateMachine.validate(current, next_status)

    with pytest.raises(ValueError, match="invalid execution order transition"):
        ExecutionOrderStateMachine.validate("created", "submitted")


def test_kill_switch_blocks_before_other_non_live_gates():
    service = PreLiveSafetyService()

    decision = service.evaluate_policy(
        _policy_input(kill_switch_active=True, broker_mode="dry_run", dry_run_enabled=False)
    )

    assert decision.decision_type == "blocked"
    assert decision.reason_code == "blocked_global_kill_switch"
    assert decision.broker_submission_allowed is False


def test_notional_over_manual_threshold_requires_operator_approval():
    service = PreLiveSafetyService()

    decision = service.evaluate_policy(
        _policy_input(quantity=6000, estimated_price=Decimal("10"))
    )

    assert decision.decision_type == "approval_required"
    assert decision.reason_code == "manual_approval_required_notional"
    assert decision.broker_submission_allowed is False


def test_sell_without_position_requires_operator_approval_when_profile_requires_it():
    service = PreLiveSafetyService()

    decision = service.evaluate_policy(
        _policy_input(side=OrderSide.SELL, quantity=100, position_quantity=0)
    )

    assert decision.decision_type == "approval_required"
    assert decision.reason_code == "manual_approval_required_sell_without_position"
    assert decision.broker_submission_allowed is False


def test_live_mode_is_always_blocked_even_when_enabled():
    service = PreLiveSafetyService()

    decision = service.evaluate_policy(
        _policy_input(broker_mode="live", live_enabled=True)
    )

    assert decision.decision_type == "blocked"
    assert decision.reason_code == "blocked_live_mode_unavailable"
    assert decision.broker_submission_allowed is False


def test_invalid_broker_mode_raises_domain_validation_error():
    service = PreLiveSafetyService()

    with pytest.raises(ValueError, match="invalid broker mode: bad-mode"):
        service.evaluate_policy(_policy_input(broker_mode="bad-mode"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"quantity": 0},
        {"quantity": -100},
        {"side": "hold"},
        {"order_type": "stop_loss"},
    ],
)
def test_malformed_order_intent_is_blocked_before_submission(overrides):
    service = PreLiveSafetyService()

    decision = service.evaluate_policy(_policy_input(**overrides))

    assert decision.decision_type == "blocked"
    assert decision.reason_code == "blocked_invalid_order_intent"
    assert decision.broker_submission_allowed is False


def test_simulated_order_within_limits_is_approved():
    service = PreLiveSafetyService()

    decision = service.evaluate_policy(_policy_input())

    assert decision.decision_type == "approved"
    assert decision.reason_code == "approved"
    assert decision.broker_submission_allowed is True


def test_stale_datetime_latest_bar_is_compared_as_date_not_datetime():
    service = PreLiveSafetyService()
    latest_bar = Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=datetime(2026, 6, 15, 15, 0, 0),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=Decimal("100000"),
    )

    decision = service.evaluate_policy(
        _policy_input(latest_bar=latest_bar, as_of=date(2026, 6, 26))
    )

    assert decision.decision_type == "blocked"
    assert decision.reason_code == "blocked_stale_market_data"


def test_buy_order_blocks_when_post_order_exposure_exceeds_limit():
    service = PreLiveSafetyService()

    decision = service.evaluate_policy(
        _policy_input(
            cash=Decimal("10000"),
            market_value=Decimal("90000"),
            peak_equity=Decimal("100000"),
            quantity=1500,
            estimated_price=Decimal("10"),
        )
    )

    assert decision.decision_type == "blocked"
    assert decision.reason_code == "blocked_max_gross_exposure"


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"latest_bar": None}, "blocked_stale_market_data"),
        ({"estimated_price": Decimal("0")}, "blocked_invalid_price"),
        ({"quantity": 10001, "estimated_price": Decimal("10")}, "blocked_max_single_order_notional"),
        ({"daily_turnover": Decimal("300000")}, "blocked_max_daily_turnover"),
        ({"daily_order_count": 20}, "blocked_max_daily_order_count"),
        ({"cash": Decimal("890000"), "peak_equity": Decimal("1000000")}, "blocked_drawdown_stop"),
        ({"cash": Decimal("0"), "market_value": Decimal("0")}, "blocked_max_gross_exposure"),
        ({"market_value": Decimal("1000001"), "cash": Decimal("-1")}, "blocked_max_gross_exposure"),
        ({"broker_mode": "dry_run", "dry_run_enabled": False}, "blocked_broker_mode_disabled"),
    ],
)
def test_policy_block_reason_codes(overrides, reason_code):
    service = PreLiveSafetyService()

    decision = service.evaluate_policy(_policy_input(**overrides))

    assert decision.decision_type == "blocked"
    assert decision.reason_code == reason_code
