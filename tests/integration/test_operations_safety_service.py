from datetime import date, datetime
from decimal import Decimal
import json

import pytest
from sqlalchemy import select

from quant_trading.core.enums import Market, OrderSide, OrderType
from quant_trading.core.models import Bar
from quant_trading.operations import PreLiveSafetyService, SafetyPolicyInput
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import ExecutionOrderDecisionORM, ExecutionOrderIntentORM
from quant_trading.storage.repositories import (
    ExecutionOrderDecisionRepository,
    ExecutionSafetyStateRepository,
    OperatorApprovalRequestRepository,
)


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def _bar(timestamp=date(2026, 6, 26), close=Decimal("10")) -> Bar:
    return Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("100000"),
    )


def _policy_input(client_order_id="order-1", **overrides) -> SafetyPolicyInput:
    payload = {
        "source_type": "paper_order",
        "source_id": 11,
        "paper_run_id": None,
        "paper_order_id": None,
        "client_order_id": client_order_id,
        "symbol": "000001",
        "instrument_id": 1,
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": 100,
        "limit_price": None,
        "estimated_price": Decimal("10"),
        "broker_mode": "simulated",
        "latest_bar": _bar(),
        "as_of": date(2026, 6, 26),
        "cash": Decimal("1000000"),
        "market_value": Decimal("0"),
        "peak_equity": Decimal("1000000"),
        "daily_turnover": Decimal("0"),
        "daily_order_count": 0,
        "position_quantity": 100,
    }
    payload.update(overrides)
    return SafetyPolicyInput(**payload)


def test_evaluate_order_intent_persists_approved_decision_and_order_state():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 30, 0)

    with session_scope(engine) as session:
        decision = PreLiveSafetyService(session).evaluate_order_intent(
            _policy_input(),
            now=now,
        )

        assert decision.decision_type == "approved"
        assert decision.reason_code == "approved"
        assert decision.order_status == "risk_approved"
        assert decision.broker_submission_allowed is True

    with session_scope(engine) as session:
        intent = session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == "order-1"
            )
        )
        decisions = session.scalars(select(ExecutionOrderDecisionORM)).all()

        assert intent.status == "risk_approved"
        assert intent.approval_required is False
        assert intent.approval_request_id is None
        assert len(decisions) == 1
        assert decisions[0].decision_type == "approved"
        assert decisions[0].reason_code == "approved"
        assert json.loads(decisions[0].policy_payload)["broker_submission_allowed"] is True


def test_kill_switch_block_persists_without_approval_request():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 30, 0)

    with session_scope(engine) as session:
        ExecutionSafetyStateRepository(session).set_kill_switch(
            active=True,
            operator="risk lead",
            reason="pause trading",
            now=now,
        )
        decision = PreLiveSafetyService(session).evaluate_order_intent(
            _policy_input(client_order_id="order-blocked"),
            now=now,
        )

        assert decision.decision_type == "blocked"
        assert decision.reason_code == "blocked_global_kill_switch"
        assert decision.order_status == "blocked"
        assert decision.broker_submission_allowed is False

    with session_scope(engine) as session:
        intent = session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == "order-blocked"
            )
        )
        approvals = OperatorApprovalRequestRepository(session).list_recent()

        assert intent.status == "blocked"
        assert intent.blocked_reason_code == "blocked_global_kill_switch"
        assert approvals == []


def test_evaluate_order_intent_creates_pending_request_and_approve_only_updates_state():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 30, 0)

    with session_scope(engine) as session:
        decision = PreLiveSafetyService(session).evaluate_order_intent(
            _policy_input(
                client_order_id="order-approval",
                quantity=6000,
                estimated_price=Decimal("10"),
            ),
            now=now,
        )

        assert decision.decision_type == "approval_required"
        assert decision.reason_code == "manual_approval_required_notional"
        assert decision.order_status == "approval_required"
        assert decision.approval_request_id is not None

    with session_scope(engine) as session:
        intent = session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == "order-approval"
            )
        )
        approval = OperatorApprovalRequestRepository(session).list_recent(status="pending")[0]
        service = PreLiveSafetyService(session)

        approved = service.approve_order_intent(
            intent.id,
            operator="risk lead",
            note="approved for pre-live dry run",
            now=now,
        )

        assert approved.decision_type == "approved"
        assert approved.reason_code == "approved"
        assert approved.order_status == "operator_approved"
        assert approved.order_intent_id == intent.id
        assert approved.broker_submission_allowed is True

    with session_scope(engine) as session:
        intent = session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == "order-approval"
            )
        )
        approval = OperatorApprovalRequestRepository(session).list_recent(status="approved")[0]
        decisions = ExecutionOrderDecisionRepository(session).list_recent()

        assert approval.status == "approved"
        assert intent.status == "operator_approved"
        assert intent.approval_required is False
        assert decisions[0].decision_type == "approved"
        assert decisions[0].reason_code == "approved"


def test_duplicate_already_evaluated_client_order_id_skips_new_decision_record():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 30, 0)

    with session_scope(engine) as session:
        service = PreLiveSafetyService(session)
        first = service.evaluate_order_intent(_policy_input(), now=now)
        duplicate = service.evaluate_order_intent(_policy_input(), now=now)

        assert first.decision_type == "approved"
        assert duplicate.decision_type == "skipped"
        assert duplicate.reason_code == "skipped_duplicate_client_order_id"
        assert duplicate.order_status == "risk_approved"
        assert duplicate.broker_submission_allowed is False
        assert len(ExecutionOrderDecisionRepository(session).list_recent()) == 1


def test_duplicate_already_evaluated_client_order_id_skips_after_safety_state_changes():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 30, 0)

    with session_scope(engine) as session:
        service = PreLiveSafetyService(session)
        first = service.evaluate_order_intent(_policy_input(), now=now)
        ExecutionSafetyStateRepository(session).set_kill_switch(
            active=True,
            operator="risk lead",
            reason="changed after first evaluation",
            now=now,
        )
        duplicate = service.evaluate_order_intent(_policy_input(), now=now)

        assert first.decision_type == "approved"
        assert duplicate.decision_type == "skipped"
        assert duplicate.reason_code == "skipped_duplicate_client_order_id"
        assert duplicate.order_status == "risk_approved"
        assert len(ExecutionOrderDecisionRepository(session).list_recent()) == 1


def test_reject_order_intent_blocks_order_without_submission():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 30, 0)

    with session_scope(engine) as session:
        PreLiveSafetyService(session).evaluate_order_intent(
            _policy_input(
                client_order_id="order-rejected",
                quantity=6000,
                estimated_price=Decimal("10"),
            ),
            now=now,
        )

    with session_scope(engine) as session:
        intent = session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == "order-rejected"
            )
        )
        approval = OperatorApprovalRequestRepository(session).list_recent(status="pending")[0]

        rejected = PreLiveSafetyService(session).reject_order_intent(
            intent.id,
            operator="risk lead",
            note="not for this session",
            now=now,
        )

        assert rejected.decision_type == "blocked"
        assert rejected.reason_code == "blocked_operator_rejected"
        assert rejected.order_status == "blocked"
        assert rejected.order_intent_id == intent.id
        assert rejected.broker_submission_allowed is False

    with session_scope(engine) as session:
        intent = session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == "order-rejected"
            )
        )
        approval = OperatorApprovalRequestRepository(session).list_recent(status="rejected")[0]
        decisions = ExecutionOrderDecisionRepository(session).list_recent()

        assert approval.status == "rejected"
        assert intent.status == "blocked"
        assert intent.blocked_reason_code == "blocked_operator_rejected"
        assert decisions[0].decision_type == "blocked"
        assert decisions[0].reason_code == "blocked_operator_rejected"


def test_approve_reject_invalid_approval_state_raises_without_new_decision():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 30, 0)

    with session_scope(engine) as session:
        PreLiveSafetyService(session).evaluate_order_intent(
            _policy_input(
                client_order_id="order-invalid-approval",
                quantity=6000,
                estimated_price=Decimal("10"),
            ),
            now=now,
        )
        intent = session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == "order-invalid-approval"
            )
        )
        PreLiveSafetyService(session).approve_order_intent(
            intent.id,
            operator="risk lead",
            note="first decision",
            now=now,
        )

        with pytest.raises(
            ValueError,
            match="approval request is not pending|invalid execution order transition",
        ):
            PreLiveSafetyService(session).reject_order_intent(
                intent.id,
                operator="risk lead",
                note="second decision",
                now=now,
            )

        assert len(ExecutionOrderDecisionRepository(session).list_recent()) == 2
