from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from quant_trading.operations.readiness import build_operations_readiness
from quant_trading.operations.safety import PreLiveSafetyDecision, PreLiveSafetyService
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import (
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    KillSwitchEventORM,
    OperatorApprovalRequestORM,
    SafetyIncidentORM,
)
from quant_trading.storage.repositories import (
    ExecutionOrderDecisionRepository,
    ExecutionOrderIntentRepository,
    ExecutionSafetyStateRepository,
    KillSwitchEventRepository,
    OperatorApprovalRequestRepository,
    SafetyIncidentRepository,
)

router = APIRouter(prefix="/ops", tags=["operations"])


class KillSwitchCommand(BaseModel):
    operator: str
    reason: str

    @field_validator("operator", "reason")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("operator and reason are required")
        return value.strip()


class OperatorNoteCommand(BaseModel):
    operator: str
    note: str

    @field_validator("operator", "note")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("operator and note are required")
        return value.strip()


@router.get("/readiness")
def get_readiness(request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        return build_operations_readiness(
            session,
            request.app.state.settings,
            _now(),
        )


@router.get("/safety-state")
def get_safety_state(request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        repo = ExecutionSafetyStateRepository(session)
        return repo.payload(repo.get_or_create_global(_now()))


@router.post("/kill-switch/enable")
def enable_kill_switch(payload: KillSwitchCommand, request: Request) -> dict[str, Any]:
    return _set_kill_switch(True, payload, request)


@router.post("/kill-switch/disable")
def disable_kill_switch(payload: KillSwitchCommand, request: Request) -> dict[str, Any]:
    return _set_kill_switch(False, payload, request)


@router.get("/kill-switch-events")
def list_kill_switch_events(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        return [
            _kill_switch_event_payload(row)
            for row in KillSwitchEventRepository(session).list_recent(limit=limit)
        ]


@router.get("/order-intents")
def list_order_intents(
    request: Request,
    status: str | None = None,
    broker_mode: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = ExecutionOrderIntentRepository(session).list_recent(
            status=status,
            broker_mode=broker_mode,
            limit=limit,
        )
        return [_order_intent_payload(row) for row in rows]


@router.get("/order-intents/{order_intent_id}")
def get_order_intent(order_intent_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = ExecutionOrderIntentRepository(session).get(order_intent_id)
        if row is None:
            raise HTTPException(status_code=404, detail="execution order intent not found")
        return _order_intent_payload(row, decisions=_decisions_for_intent(session, row.id))


@router.post("/order-intents/{order_intent_id}/approve")
def approve_order_intent(
    order_intent_id: int,
    payload: OperatorNoteCommand,
    request: Request,
) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        try:
            decision = PreLiveSafetyService(session).approve_order_intent(
                order_intent_id,
                operator=payload.operator,
                note=payload.note,
                now=_now(),
            )
        except ValueError as exc:
            raise _approval_http_error(exc) from exc
        return _safety_decision_payload(decision)


@router.post("/order-intents/{order_intent_id}/reject")
def reject_order_intent(
    order_intent_id: int,
    payload: OperatorNoteCommand,
    request: Request,
) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        try:
            decision = PreLiveSafetyService(session).reject_order_intent(
                order_intent_id,
                operator=payload.operator,
                note=payload.note,
                now=_now(),
            )
        except ValueError as exc:
            raise _approval_http_error(exc) from exc
        return _safety_decision_payload(decision)


@router.get("/approval-requests")
def list_approval_requests(
    request: Request,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        return [
            _approval_request_payload(row)
            for row in OperatorApprovalRequestRepository(session).list_recent(
                status=status,
                limit=limit,
            )
        ]


@router.get("/incidents")
def list_incidents(
    request: Request,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        return [
            _incident_payload(row)
            for row in SafetyIncidentRepository(session).list_recent(
                status=status,
                severity=severity,
                limit=limit,
            )
        ]


@router.post("/incidents/{incident_id}/acknowledge")
def acknowledge_incident(
    incident_id: int,
    payload: OperatorNoteCommand,
    request: Request,
) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        incident_repo = SafetyIncidentRepository(session)
        row = incident_repo.get(incident_id)
        if row is None:
            raise HTTPException(status_code=404, detail="incident not found")
        try:
            return _incident_payload(
                incident_repo.acknowledge(
                    row,
                    operator=payload.operator,
                    acknowledged_at=_now(),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(
    incident_id: int,
    payload: OperatorNoteCommand,
    request: Request,
) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        incident_repo = SafetyIncidentRepository(session)
        row = incident_repo.get(incident_id)
        if row is None:
            raise HTTPException(status_code=404, detail="incident not found")
        try:
            return _incident_payload(
                incident_repo.resolve(
                    row,
                    operator=payload.operator,
                    resolved_at=_now(),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


def _set_kill_switch(
    active: bool,
    payload: KillSwitchCommand,
    request: Request,
) -> dict[str, Any]:
    now = _now()
    with session_scope(request.app.state.engine) as session:
        safety_repo = ExecutionSafetyStateRepository(session)
        state = safety_repo.get_or_create_global(now)
        previous_payload = safety_repo.payload(state)
        state = safety_repo.set_kill_switch(
            active=active,
            operator=payload.operator,
            reason=payload.reason,
            now=now,
        )
        new_payload = safety_repo.payload(state)
        KillSwitchEventRepository(session).record(
            scope=state.scope,
            previous_state_payload=previous_payload,
            new_state_payload=new_payload,
            operator=payload.operator,
            reason=payload.reason,
            created_at=now,
        )
        return new_payload


def _approval_http_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if message.startswith("execution order intent not found"):
        return HTTPException(status_code=404, detail="execution order intent not found")
    if message.startswith("approval request not found"):
        return HTTPException(status_code=404, detail="approval request not found")
    if (
        "invalid execution order transition" in message
        or message == "approval request is not pending"
        or message == "order intent has no approval request"
        or message == "approval request does not match execution order intent"
    ):
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=400, detail=message)


def _safety_decision_payload(decision: PreLiveSafetyDecision) -> dict[str, Any]:
    return {
        "decision_type": decision.decision_type,
        "reason_code": decision.reason_code,
        "message": decision.message,
        "broker_submission_allowed": False,
        "live_execution_available": False,
        "order_status": decision.order_status,
        "order_intent_id": decision.order_intent_id,
        "approval_request_id": decision.approval_request_id,
    }


def _order_intent_payload(
    row: ExecutionOrderIntentORM,
    decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "paper_run_id": row.paper_run_id,
        "paper_order_id": row.paper_order_id,
        "client_order_id": row.client_order_id,
        "symbol": row.symbol,
        "instrument_id": row.instrument_id,
        "side": row.side,
        "order_type": row.order_type,
        "quantity": row.quantity,
        "limit_price": _decimal_str(row.limit_price),
        "estimated_price": _decimal_str(row.estimated_price),
        "estimated_notional": _decimal_str(row.estimated_notional),
        "broker_mode": row.broker_mode,
        "status": row.status,
        "risk_profile_name": row.risk_profile_name,
        "risk_summary_payload": _json_loads(row.risk_summary_payload),
        "approval_required": row.approval_required,
        "approval_request_id": row.approval_request_id,
        "blocked_reason_code": row.blocked_reason_code,
        "blocked_reason": row.blocked_reason,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "submitted_at": _iso(row.submitted_at),
    }
    if decisions is not None:
        payload["decisions"] = decisions
    return payload


def _decisions_for_intent(session, order_intent_id: int) -> list[dict[str, Any]]:
    return [
        _order_decision_payload(row)
        for row in ExecutionOrderDecisionRepository(session).list_recent(limit=100)
        if row.order_intent_id == order_intent_id
    ]


def _order_decision_payload(row: ExecutionOrderDecisionORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "order_intent_id": row.order_intent_id,
        "decision_type": row.decision_type,
        "reason_code": row.reason_code,
        "message": row.message,
        "policy_payload": _json_loads(row.policy_payload),
        "created_at": _iso(row.created_at),
    }


def _approval_request_payload(row: OperatorApprovalRequestORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "status": row.status,
        "reason_code": row.reason_code,
        "requested_by": row.requested_by,
        "requested_at": _iso(row.requested_at),
        "decided_by": row.decided_by,
        "decided_at": _iso(row.decided_at),
        "operator_note": row.operator_note,
        "expires_at": _iso(row.expires_at),
    }


def _incident_payload(row: SafetyIncidentORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "severity": row.severity,
        "category": row.category,
        "status": row.status,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "reason_code": row.reason_code,
        "message": row.message,
        "payload": _json_loads(row.payload),
        "created_at": _iso(row.created_at),
        "acknowledged_by": row.acknowledged_by,
        "acknowledged_at": _iso(row.acknowledged_at),
        "resolved_by": row.resolved_by,
        "resolved_at": _iso(row.resolved_at),
    }


def _kill_switch_event_payload(row: KillSwitchEventORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "scope": row.scope,
        "previous_state_payload": _json_loads(row.previous_state_payload),
        "new_state_payload": _json_loads(row.new_state_payload),
        "operator": row.operator,
        "reason": row.reason,
        "created_at": _iso(row.created_at),
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _decimal_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
