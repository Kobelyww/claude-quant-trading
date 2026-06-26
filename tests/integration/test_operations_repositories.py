from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import ExecutionOrderIntentORM
from quant_trading.storage.repositories import (
    ExecutionOrderDecisionRepository,
    ExecutionOrderIntentRepository,
    ExecutionSafetyStateRepository,
    KillSwitchEventRepository,
    OperatorApprovalRequestRepository,
    SafetyIncidentRepository,
)


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_safety_state_repository_seeds_global_state_and_records_kill_switch_event():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)

    with session_scope(engine) as session:
        safety_repo = ExecutionSafetyStateRepository(session)
        state = safety_repo.get_or_create_global(now=now)
        previous_payload = safety_repo.payload(state)

        assert state.scope == "global"
        assert state.kill_switch_active is False
        assert state.dry_run_enabled is True
        assert state.simulated_enabled is True
        assert state.live_enabled is False
        assert state.reason == "default simulated and dry-run startup"
        assert state.updated_by == "system"

        state = safety_repo.set_kill_switch(
            active=True,
            operator="risk lead",
            reason="pause while checking provider data",
            now=now + timedelta(minutes=1),
        )
        new_payload = safety_repo.payload(state)
        KillSwitchEventRepository(session).record(
            scope=state.scope,
            previous_state_payload=previous_payload,
            new_state_payload=new_payload,
            operator="risk lead",
            reason="pause while checking provider data",
            created_at=now + timedelta(minutes=1),
        )

    with session_scope(engine) as session:
        state = ExecutionSafetyStateRepository(session).get_global()
        events = KillSwitchEventRepository(session).list_recent()

        assert state.kill_switch_active is True
        assert state.reason == "pause while checking provider data"
        assert state.updated_by == "risk lead"
        assert len(events) == 1
        assert events[0].operator == "risk lead"
        assert json.loads(events[0].previous_state_payload)["kill_switch_active"] is False
        assert json.loads(events[0].new_state_payload)["kill_switch_active"] is True


def test_order_intent_repository_is_idempotent_for_matching_payload():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = {
        "source_type": "paper_order",
        "source_id": 7,
        "paper_run_id": None,
        "paper_order_id": None,
        "client_order_id": "paper-7-11",
        "symbol": "000001",
        "instrument_id": 1,
        "side": "buy",
        "order_type": "market",
        "quantity": 100,
        "limit_price": None,
        "estimated_price": Decimal("10"),
        "estimated_notional": Decimal("1000"),
        "broker_mode": "simulated",
        "risk_profile_name": "default",
        "risk_summary_payload": {"checks": []},
        "approval_required": False,
        "created_at": now,
        "updated_at": now,
    }

    with session_scope(engine) as session:
        repo = ExecutionOrderIntentRepository(session)
        row, created = repo.get_or_create(**payload)
        same_row, same_created = repo.get_or_create(**payload)

        assert row.id == same_row.id
        assert created is True
        assert same_created is False
        assert same_row.status == "created"
        assert json.loads(same_row.risk_summary_payload) == {"checks": []}


def test_order_intent_repository_rejects_conflicting_duplicate_client_order_id():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = {
        "source_type": "paper_order",
        "source_id": 7,
        "paper_run_id": None,
        "paper_order_id": None,
        "client_order_id": "paper-7-11",
        "symbol": "000001",
        "instrument_id": 1,
        "side": "buy",
        "order_type": "market",
        "quantity": 100,
        "limit_price": None,
        "estimated_price": Decimal("10"),
        "estimated_notional": Decimal("1000"),
        "broker_mode": "simulated",
        "risk_profile_name": "default",
        "risk_summary_payload": {"checks": []},
        "approval_required": False,
        "created_at": now,
        "updated_at": now,
    }

    with session_scope(engine) as session:
        repo = ExecutionOrderIntentRepository(session)
        repo.get_or_create(**payload)

        with pytest.raises(
            ValueError,
            match="^client_order_id already exists with different payload$",
        ):
            repo.get_or_create(
                **{
                    **payload,
                    "quantity": 200,
                    "estimated_notional": Decimal("2000"),
                }
            )


def test_decisions_approvals_and_incidents_are_persisted_with_capped_messages():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)

    with session_scope(engine) as session:
        intent = ExecutionOrderIntentORM(
            source_type="manual",
            source_id=None,
            client_order_id="manual-1",
            symbol="000001",
            instrument_id=1,
            side="buy",
            order_type="market",
            quantity=100,
            estimated_notional=Decimal("1000"),
            broker_mode="simulated",
            risk_profile_name="default",
            created_at=now,
            updated_at=now,
        )
        session.add(intent)
        session.flush()

        decision = ExecutionOrderDecisionRepository(session).record(
            order_intent_id=intent.id,
            decision_type="blocked",
            reason_code="provider_stale",
            message="x" * 2000,
            policy_payload={"order_intent_id": intent.id},
            created_at=now,
        )
        approval = OperatorApprovalRequestRepository(session).create_pending(
            resource_type="execution_order_intent",
            resource_id=intent.id,
            reason_code="requires_operator",
            requested_by="system",
            requested_at=now,
            expires_at=now + timedelta(hours=1),
        )
        same_approval = OperatorApprovalRequestRepository(session).create_pending(
            resource_type="execution_order_intent",
            resource_id=intent.id,
            reason_code="requires_operator",
            requested_by="another operator",
            requested_at=now + timedelta(minutes=1),
            expires_at=now + timedelta(hours=2),
        )
        incident = SafetyIncidentRepository(session).create(
            severity="high",
            category="execution_safety",
            resource_type="execution_order_intent",
            resource_id=intent.id,
            reason_code="provider_stale",
            message="y" * 3000,
            payload={"order_intent_id": intent.id},
            created_at=now,
        )

        assert len(decision.message) == 1024
        assert json.loads(decision.policy_payload) == {"order_intent_id": intent.id}
        assert approval.id == same_approval.id
        assert approval.status == "pending"
        assert approval.reason_code == "requires_operator"
        assert len(incident.message) == 2048
        assert json.loads(incident.payload)["order_intent_id"] == intent.id
