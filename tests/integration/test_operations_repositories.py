from datetime import date, datetime, timedelta
from decimal import Decimal
import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_trading.storage.db import (
    create_all,
    make_engine,
    make_session_factory,
    session_scope,
)
from quant_trading.storage.models import (
    ExecutionOrderIntentORM,
    OperatorApprovalRequestORM,
)
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


def _order_intent_payload(now: datetime, **overrides):
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
    payload.update(overrides)
    return payload


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
    payload = _order_intent_payload(now)

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
    payload = _order_intent_payload(now)

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


def test_order_intent_repository_compares_unsanitized_payload_for_idempotency():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    common_prefix = "a" * 600
    payload = _order_intent_payload(
        now,
        client_order_id="paper-long-risk-summary",
        risk_summary_payload={"checks": [{"details": common_prefix + "first"}]},
    )

    with session_scope(engine) as session:
        repo = ExecutionOrderIntentRepository(session)
        row, created = repo.get_or_create(**payload)
        same_row, same_created = repo.get_or_create(**payload)

        assert created is True
        assert same_created is False
        assert same_row.id == row.id

        with pytest.raises(
            ValueError,
            match="^client_order_id already exists with different payload$",
        ):
            repo.get_or_create(
                **{
                    **payload,
                    "risk_summary_payload": {
                        "checks": [{"details": common_prefix + "second"}],
                    },
                }
            )


def test_order_intent_repository_treats_reordered_risk_payload_as_idempotent():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = _order_intent_payload(
        now,
        client_order_id="paper-reordered-risk-summary",
        risk_summary_payload={"a": 1, "b": 2},
    )

    with session_scope(engine) as session:
        repo = ExecutionOrderIntentRepository(session)
        row, created = repo.get_or_create(**payload)
        same_row, same_created = repo.get_or_create(
            **{
                **payload,
                "risk_summary_payload": {"b": 2, "a": 1},
            }
        )

        assert created is True
        assert same_created is False
        assert same_row.id == row.id


def test_order_intent_repository_treats_decimal_scale_risk_payload_as_idempotent():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = _order_intent_payload(
        now,
        client_order_id="paper-decimal-scale-risk-summary",
        risk_summary_payload={"checks": [{"limit": Decimal("10.000000")}]},
    )

    with session_scope(engine) as session:
        repo = ExecutionOrderIntentRepository(session)
        row, created = repo.get_or_create(**payload)
        same_row, same_created = repo.get_or_create(
            **{
                **payload,
                "risk_summary_payload": {"checks": [{"limit": Decimal("10.0")}]},
            }
        )

        assert created is True
        assert same_created is False
        assert same_row.id == row.id


def test_order_intent_repository_rejects_decimal_string_risk_payload_collision():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = _order_intent_payload(
        now,
        client_order_id="paper-decimal-string-risk-summary",
        risk_summary_payload={"value": Decimal("10.0")},
    )

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
                    "risk_summary_payload": {"value": "10"},
                }
            )


def test_order_intent_repository_rejects_date_string_risk_payload_collision():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = _order_intent_payload(
        now,
        client_order_id="paper-date-string-risk-summary",
        risk_summary_payload={"as_of": date(2026, 6, 26)},
    )

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
                    "risk_summary_payload": {"as_of": "2026-06-26"},
                }
            )


def test_order_intent_status_caps_blocked_reason():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = _order_intent_payload(now)

    with session_scope(engine) as session:
        repo = ExecutionOrderIntentRepository(session)
        row, _ = repo.get_or_create(**payload)
        repo.set_status(
            row,
            "blocked",
            now + timedelta(minutes=1),
            blocked_reason_code="risk_limit",
            blocked_reason="x" * 2000,
        )

        assert row.blocked_reason_code == "risk_limit"
        assert len(row.blocked_reason) == 1024


def test_order_intent_retry_ignores_mutable_approval_required_state():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = _order_intent_payload(now)

    with session_scope(engine) as session:
        repo = ExecutionOrderIntentRepository(session)
        row, created = repo.get_or_create(**payload)
        repo.set_status(
            row,
            "approval_required",
            now + timedelta(minutes=1),
            approval_required=True,
        )
        same_row, same_created = repo.get_or_create(**payload)

        assert created is True
        assert same_created is False
        assert same_row.id == row.id
        assert same_row.approval_required is True


def test_order_intent_repository_recovers_duplicate_insert_as_idempotent(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "ops.sqlite3"
    engine = make_engine(f"sqlite+pysqlite:///{db_path}")
    create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = _order_intent_payload(now)
    session_a: Session = factory()
    session_b: Session = factory()
    try:
        assert ExecutionOrderIntentRepository(session_b).get_by_client_order_id(
            "paper-7-11"
        ) is None

        row_a, created_a = ExecutionOrderIntentRepository(session_a).get_or_create(
            **payload
        )
        session_a.commit()

        repo_b = ExecutionOrderIntentRepository(session_b)
        original_get = repo_b.get_by_client_order_id
        calls = 0

        def stale_first_read(client_order_id: str):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return original_get(client_order_id)

        monkeypatch.setattr(repo_b, "get_by_client_order_id", stale_first_read)
        row_b, created_b = repo_b.get_or_create(**payload)
        session_b.commit()

        assert created_a is True
        assert created_b is False
        assert row_b.id == row_a.id
        assert calls >= 2
    finally:
        session_b.close()
        session_a.close()


def test_pending_approval_requests_have_database_unique_guard():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    factory = make_session_factory(engine)
    session = factory()
    try:
        session.add(
            OperatorApprovalRequestORM(
                resource_type="execution_order_intent",
                resource_id=9,
                status="pending",
                reason_code="manual_review",
                requested_by="system",
                requested_at=now,
            )
        )
        session.flush()
        session.add(
            OperatorApprovalRequestORM(
                resource_type="execution_order_intent",
                resource_id=9,
                status="pending",
                reason_code="manual_review",
                requested_by="system",
                requested_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        session.rollback()
        session.close()


def test_approval_repository_recovers_duplicate_pending_insert_as_existing(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "ops.sqlite3"
    engine = make_engine(f"sqlite+pysqlite:///{db_path}")
    create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 6, 26, 9, 0, 0)
    session_a: Session = factory()
    session_b: Session = factory()
    try:
        row_a = OperatorApprovalRequestRepository(session_a).create_pending(
            resource_type="execution_order_intent",
            resource_id=17,
            reason_code="manual_review",
            requested_by="system",
            requested_at=now,
            expires_at=None,
        )
        session_a.commit()

        repo_b = OperatorApprovalRequestRepository(session_b)
        original_get = repo_b.get_active_for_resource
        calls = 0

        def stale_first_read(resource_type: str, resource_id: int):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return original_get(resource_type, resource_id)

        monkeypatch.setattr(repo_b, "get_active_for_resource", stale_first_read)
        row_b = repo_b.get_or_create_active(
            resource_type="execution_order_intent",
            resource_id=17,
            reason_code="manual_review",
            requested_by="risk lead",
            requested_at=now + timedelta(minutes=1),
            expires_at=None,
        )
        session_b.commit()

        assert row_b.id == row_a.id
        assert row_b.requested_by == "system"
        assert calls >= 2
    finally:
        session_b.close()
        session_a.close()


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


def test_approval_repository_rejects_invalid_decision_status_without_persisting():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)

    with session_scope(engine) as session:
        approval = OperatorApprovalRequestRepository(session).create_pending(
            resource_type="execution_order_intent",
            resource_id=31,
            reason_code="requires_operator",
            requested_by="system",
            requested_at=now,
            expires_at=None,
        )

        with pytest.raises(ValueError, match="^invalid approval decision status: typo$"):
            OperatorApprovalRequestRepository(session).decide(
                approval,
                status="typo",
                operator="risk lead",
                note="bad status",
                decided_at=now + timedelta(minutes=1),
            )

        session.expire(approval)
        persisted = session.get(OperatorApprovalRequestORM, approval.id)
        assert persisted.status == "pending"
        assert persisted.decided_by is None
        assert persisted.decided_at is None
        assert persisted.operator_note == ""


def test_ops_payloads_are_bounded_and_sanitize_secret_like_values():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 26, 9, 0, 0)
    long_text = "a" * 9000

    with session_scope(engine) as session:
        intent_repo = ExecutionOrderIntentRepository(session)
        intent, _ = intent_repo.get_or_create(
            **_order_intent_payload(
                now,
                client_order_id="secret-payload-1",
                risk_summary_payload={
                    "checks": [{"name": "notional", "status": "ok"}],
                    "api_key": "secret-key-value",
                    "notes": long_text,
                },
            )
        )
        decision = ExecutionOrderDecisionRepository(session).record(
            order_intent_id=intent.id,
            decision_type="blocked",
            reason_code="oversized_payload",
            message="bounded",
            policy_payload={
                "order_intent_id": intent.id,
                "token": "secret-token-value",
                "notes": long_text,
            },
            created_at=now,
        )
        incident = SafetyIncidentRepository(session).create(
            severity="high",
            category="execution_safety",
            resource_type="execution_order_intent",
            resource_id=intent.id,
            reason_code="oversized_payload",
            message="bounded",
            payload={
                "order_intent_id": intent.id,
                "password": "secret-password-value",
                "details": long_text,
            },
            created_at=now,
        )
        KillSwitchEventRepository(session).record(
            scope="global",
            previous_state_payload={
                "kill_switch_active": False,
                "secret": "previous-secret",
                "details": long_text,
            },
            new_state_payload={
                "kill_switch_active": True,
                "access_token": "new-secret",
                "details": long_text,
            },
            operator="risk lead",
            reason="bounded",
            created_at=now,
        )

    with session_scope(engine) as session:
        intent = session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == "secret-payload-1"
            )
        )
        event = KillSwitchEventRepository(session).list_recent()[0]
        payloads = [
            intent.risk_summary_payload,
            decision.policy_payload,
            incident.payload,
            event.previous_state_payload,
            event.new_state_payload,
        ]
        for payload_text in payloads:
            assert len(payload_text) <= 4096
            assert "secret-key-value" not in payload_text
            assert "secret-token-value" not in payload_text
            assert "secret-password-value" not in payload_text
            assert "previous-secret" not in payload_text
            assert "new-secret" not in payload_text
        assert json.loads(intent.risk_summary_payload)["checks"][0]["name"] == "notional"
        assert json.loads(decision.policy_payload)["token"] == "[REDACTED]"
        assert json.loads(incident.payload)["order_intent_id"] == intent.id
        assert json.loads(event.new_state_payload)["kill_switch_active"] is True
