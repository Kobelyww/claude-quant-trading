from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.core.enums import Market, OrderSide, OrderType
from quant_trading.core.models import Bar
from quant_trading.operations import PreLiveSafetyService, SafetyPolicyInput
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    DataQualityReportORM,
    DataSyncRunORM,
    ExecutionOrderIntentORM,
    JobRunORM,
    KillSwitchEventORM,
    SafetyIncidentORM,
)
from quant_trading.storage.repositories import (
    OperatorApprovalRequestRepository,
    SafetyIncidentRepository,
)


def make_client(settings: AppSettings | None = None) -> tuple[TestClient, object]:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine=engine, settings=settings or AppSettings())), engine


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


def _policy_input(client_order_id: str = "ops-order-1", **overrides) -> SafetyPolicyInput:
    payload = {
        "source_type": "paper_run",
        "source_id": 11,
        "paper_run_id": None,
        "paper_order_id": None,
        "client_order_id": client_order_id,
        "symbol": "000001",
        "instrument_id": 1,
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": 6000,
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


def test_readiness_defaults_to_pre_live_non_live_posture():
    client, engine = make_client()
    now = datetime.now(UTC).replace(tzinfo=None)

    with session_scope(engine) as session:
        session.add(
            DataSyncRunORM(
                provider="akshare",
                symbol="000001",
                status="succeeded",
                imported_bars=120,
                started_at=now - timedelta(minutes=4),
                finished_at=now - timedelta(minutes=3),
                created_at=now - timedelta(minutes=4),
            )
        )
        session.add(
            DataQualityReportORM(
                symbol="000001",
                source="akshare",
                status="passed",
                severity="none",
                stale_data=True,
                created_at=now - timedelta(minutes=2),
                finished_at=now - timedelta(minutes=1),
            )
        )
        session.add(
            JobRunORM(
                job_type="market_data_sync",
                status="failed",
                error_message="provider unavailable",
                queued_at=now - timedelta(hours=1),
                finished_at=now - timedelta(minutes=40),
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(minutes=40),
            )
        )

    response = client.get("/ops/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["environment"] == "local"
    assert payload["trading_enabled"] is False
    assert payload["broker_mode"] == "simulated"
    assert payload["global_kill_switch_active"] is False
    assert payload["live_execution_available"] is False
    assert payload["safe_for_simulated_paper"] is True
    assert payload["safe_for_dry_run"] is True
    assert payload["safe_for_live"] is False
    assert "live_execution_unavailable" in payload["reasons"]
    assert payload["open_critical_incidents"] == 0
    assert payload["open_warning_incidents"] == 0
    assert payload["pending_approval_requests"] == 0
    assert payload["latest_data_sync_status"] == "succeeded"
    assert payload["latest_research_validation_status"] is None
    assert payload["open_incidents"] == {"critical": 0, "warning": 0}
    assert payload["pending_approvals"] == 0
    assert payload["stuck_jobs"] == 0
    assert payload["failed_jobs_24h"] == 1
    assert payload["stale_data_reports"] == 1
    assert payload["latest_data_sync"]["status"] == "succeeded"
    assert payload["latest_research_validation"] is None


def test_acknowledged_critical_incident_blocks_readiness_until_resolved():
    client, engine = make_client()

    with session_scope(engine) as session:
        incident = SafetyIncidentRepository(session).create(
            severity="critical",
            category="execution_safety",
            resource_type=None,
            resource_id=None,
            reason_code="provider_stale",
            message="provider data stale",
            payload={"symbol": "000001"},
            created_at=datetime(2026, 6, 26, 9, 0, 0),
        )
        incident_id = incident.id

    open_readiness = client.get("/ops/readiness").json()
    assert open_readiness["open_critical_incidents"] == 1
    assert open_readiness["safe_for_simulated_paper"] is False
    assert open_readiness["safe_for_dry_run"] is False
    assert "open_critical_incidents" in open_readiness["reasons"]

    acknowledge = client.post(
        f"/ops/incidents/{incident_id}/acknowledge",
        json={"operator": "ops lead", "note": "checking provider"},
    )
    assert acknowledge.status_code == 200

    acknowledged_readiness = client.get("/ops/readiness").json()
    assert acknowledged_readiness["open_critical_incidents"] == 1
    assert acknowledged_readiness["safe_for_simulated_paper"] is False
    assert acknowledged_readiness["safe_for_dry_run"] is False
    assert "open_critical_incidents" in acknowledged_readiness["reasons"]

    resolve = client.post(
        f"/ops/incidents/{incident_id}/resolve",
        json={"operator": "ops lead", "note": "provider recovered"},
    )
    assert resolve.status_code == 200

    resolved_readiness = client.get("/ops/readiness").json()
    assert resolved_readiness["open_critical_incidents"] == 0
    assert resolved_readiness["safe_for_simulated_paper"] is True
    assert resolved_readiness["safe_for_dry_run"] is True
    assert "open_critical_incidents" not in resolved_readiness["reasons"]


def test_kill_switch_enable_disable_writes_events_and_updates_readiness():
    client, engine = make_client()

    enabled = client.post(
        "/ops/kill-switch/enable",
        json={"operator": "risk lead", "reason": "pause pre-live checks"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["kill_switch_active"] is True

    readiness = client.get("/ops/readiness").json()
    assert readiness["global_kill_switch_active"] is True
    assert readiness["safe_for_simulated_paper"] is False
    assert readiness["safe_for_dry_run"] is False
    assert "global_kill_switch_active" in readiness["reasons"]

    disabled = client.post(
        "/ops/kill-switch/disable",
        json={"operator": "risk lead", "reason": "checks cleared"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["kill_switch_active"] is False

    events_response = client.get("/ops/kill-switch-events")
    assert events_response.status_code == 200
    events = events_response.json()
    assert [event["new_state_payload"]["kill_switch_active"] for event in events] == [
        False,
        True,
    ]

    with session_scope(engine) as session:
        assert len(session.scalars(select(KillSwitchEventORM)).all()) == 2


def test_incident_acknowledge_resolve_and_invalid_transition_mapping():
    client, engine = make_client()

    with session_scope(engine) as session:
        incident = SafetyIncidentRepository(session).create(
            severity="critical",
            category="execution_safety",
            resource_type=None,
            resource_id=None,
            reason_code="provider_stale",
            message="provider data stale",
            payload={"symbol": "000001"},
            created_at=datetime(2026, 6, 26, 9, 0, 0),
        )
        incident_id = incident.id

    acknowledge = client.post(
        f"/ops/incidents/{incident_id}/acknowledge",
        json={"operator": "ops lead", "note": "checking provider"},
    )
    assert acknowledge.status_code == 200
    assert acknowledge.json()["status"] == "acknowledged"
    assert acknowledge.json()["acknowledged_by"] == "ops lead"

    resolve = client.post(
        f"/ops/incidents/{incident_id}/resolve",
        json={"operator": "ops lead", "note": "provider recovered"},
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "resolved"
    assert resolve.json()["resolved_by"] == "ops lead"
    first_resolved_at = resolve.json()["resolved_at"]

    duplicate_resolve = client.post(
        f"/ops/incidents/{incident_id}/resolve",
        json={"operator": "ops lead", "note": "already recovered"},
    )
    assert duplicate_resolve.status_code == 409
    assert duplicate_resolve.json() == {"detail": "incident is already resolved"}

    persisted = client.get("/ops/incidents").json()[0]
    assert persisted["id"] == incident_id
    assert persisted["resolved_at"] == first_resolved_at

    conflict = client.post(
        f"/ops/incidents/{incident_id}/acknowledge",
        json={"operator": "ops lead", "note": "late ack"},
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "incident is already resolved"}

    missing = client.post(
        "/ops/incidents/9999/resolve",
        json={"operator": "ops lead", "note": "not found"},
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "incident not found"}


def test_operations_command_routes_are_auth_protected_when_auth_enabled():
    settings = AppSettings(require_auth=True, api_token="local-token")
    client, _ = make_client(settings)

    response = client.post(
        "/ops/kill-switch/enable",
        json={"operator": "risk lead", "reason": "pause"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}

    authorized = client.post(
        "/ops/kill-switch/enable",
        json={"operator": "risk lead", "reason": "pause"},
        headers={"Authorization": "Bearer local-token"},
    )
    assert authorized.status_code == 200


def test_operations_commands_reject_blank_operator_and_reason_or_note():
    client, _ = make_client()

    kill_switch = client.post(
        "/ops/kill-switch/enable",
        json={"operator": " ", "reason": "pause"},
    )
    assert kill_switch.status_code == 400

    incident = client.post(
        "/ops/incidents/1/acknowledge",
        json={"operator": "ops", "note": ""},
    )
    assert incident.status_code == 400

    overlong = client.post(
        "/ops/kill-switch/enable",
        json={"operator": "x" * 129, "reason": "pause"},
    )
    assert overlong.status_code == 400


def test_order_intent_get_includes_decisions_and_approval_404_409_mapping():
    client, engine = make_client()
    now = datetime(2026, 6, 26, 9, 30, 0)

    with session_scope(engine) as session:
        decision = PreLiveSafetyService(session).evaluate_order_intent(
            _policy_input(),
            now=now,
        )
        intent_id = decision.order_intent_id

    detail = client.get(f"/ops/order-intents/{intent_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "approval_required"
    assert detail.json()["decisions"][0]["reason_code"] == "manual_approval_required_notional"

    missing = client.post(
        "/ops/order-intents/9999/approve",
        json={"operator": "risk lead", "note": "approve"},
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "execution order intent not found"}

    approved = client.post(
        f"/ops/order-intents/{intent_id}/approve",
        json={"operator": "risk lead", "note": "approved for dry run"},
    )
    assert approved.status_code == 200
    assert approved.json()["broker_submission_allowed"] is False
    assert approved.json()["order_status"] == "operator_approved"

    duplicate = client.post(
        f"/ops/order-intents/{intent_id}/approve",
        json={"operator": "risk lead", "note": "again"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"].startswith("invalid execution order transition")

    with session_scope(engine) as session:
        intent = session.get(ExecutionOrderIntentORM, intent_id)
        approval = OperatorApprovalRequestRepository(session).get(
            intent.approval_request_id
        )
        assert intent.status == "operator_approved"
        assert approval.status == "approved"
