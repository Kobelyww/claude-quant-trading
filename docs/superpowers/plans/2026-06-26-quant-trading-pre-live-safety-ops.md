# Quant Trading Pre-Live Safety Ops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pre-live safety and operations layer that records execution-bound order intents, applies policy gates, supports operator approvals and kill-switch events, and exposes readiness without adding real broker execution.

**Architecture:** Add operational storage tables and repositories first, then build a focused `quant_trading.operations` service layer for policy evaluation and readiness. Integrate that service into the existing paper engine before broker adapter submission, then expose protected FastAPI routes, dashboard status, README documentation, and full verification.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, pytest, existing paper engine, existing simulated/dry-run broker adapter boundary, existing server-rendered dashboard.

---

## Branch And Scope Notes

- Working directory: `/Users/haobowang/Desktop/Code file/Python/LLM-Study/quant-trading/.worktrees/quant-agent-v1`
- Working branch: `codex/quant-agent-v3-approval-review-loop`
- Design spec: `docs/superpowers/specs/2026-06-26-quant-trading-pre-live-safety-ops-design.md`
- This milestone remains research and paper-only.
- Do not add real broker SDKs, exchange APIs, credential storage, live broker modes, public live order submission APIs, generated strategy execution, or automatic promotion from research validation to execution.
- Preserve default simulated paper trading when the global kill switch is inactive and policy checks pass.

## File Structure

- Modify: `src/quant_trading/storage/models.py`
  - Add `ExecutionSafetyStateORM`, `ExecutionOrderIntentORM`, `ExecutionOrderDecisionORM`, `OperatorApprovalRequestORM`, `SafetyIncidentORM`, and `KillSwitchEventORM`.
- Modify: `src/quant_trading/storage/repositories.py`
  - Add small repositories for operational storage and JSON-safe payload handling.
- Create: `migrations/versions/20260626_0010_add_pre_live_safety_ops.py`
  - Add the six operations tables and seed default global safety state.
- Modify: `tests/integration/test_migrations.py`
  - Assert new tables, columns, indexes, defaults, and default safety-state seed.
- Create: `tests/integration/test_operations_repositories.py`
  - Cover repository lifecycle, idempotent order intents, decisions, approval requests, incidents, kill-switch events, and payload capping.
- Create: `src/quant_trading/operations/__init__.py`
  - Export service-level types used outside the package.
- Create: `src/quant_trading/operations/safety.py`
  - Define risk profile, decision model, state transition validation, and `PreLiveSafetyService`.
- Create: `src/quant_trading/operations/readiness.py`
  - Build compact operational readiness summaries for API and dashboard use.
- Create: `tests/unit/test_operations_safety.py`
  - Unit coverage for profile validation, reason codes, state transitions, policy decisions, and duplicate client order handling.
- Create: `tests/integration/test_operations_safety_service.py`
  - Integration coverage for persisted safety decisions and operator approval transitions.
- Modify: `src/quant_trading/paper/engine.py`
  - Evaluate `PreLiveSafetyService` after existing risk approval and before broker adapter submission.
- Modify: `src/quant_trading/workflows/operations.py`
  - Construct the paper engine with default pre-live safety enabled.
- Modify: `tests/integration/test_paper_engine.py`
  - Assert approved, blocked, approval-required, and dry-run paths.
- Create: `src/quant_trading/api/routes/operations.py`
  - Add `/ops/readiness`, `/ops/safety-state`, `/ops/order-intents`, `/ops/approval-requests`, `/ops/incidents`, and `/ops/kill-switch-events`.
- Modify: `src/quant_trading/api/main.py`
  - Register the operations router.
- Create: `tests/integration/test_operations_api.py`
  - HTTP coverage for read APIs, kill-switch commands, approvals, incidents, and auth-protected command behavior.
- Modify: `src/quant_trading/api/routes/dashboard.py`
  - Add an `Operations Safety` dashboard section using server-rendered patterns.
- Modify: `tests/integration/test_dashboard.py`
  - Assert the dashboard renders safety state, readiness booleans, approval counts, incident counts, recent decisions, and kill-switch events.
- Modify: `README.md`
  - Document the safety workflow, endpoints, defaults, and non-live constraints.

## Review Protocol For Every Implementation Task

Each task must finish with both checks before commit:

1. **Spec review:** Compare the task against `docs/superpowers/specs/2026-06-26-quant-trading-pre-live-safety-ops-design.md`. Confirm every changed behavior is in scope and no non-goal behavior slipped in.
2. **Quality review:** Check naming, state transitions, JSON payload bounds, migration reversibility, transaction boundaries, API error mapping, secrets handling, broker/paper isolation, and test coverage.

Record the review result in the task notes before committing. If either review fails, fix it before the next task.

---

### Task 1: Operations Storage, Migration, And Repositories

**Files:**
- Modify: `src/quant_trading/storage/models.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `migrations/versions/20260626_0010_add_pre_live_safety_ops.py`
- Modify: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_operations_repositories.py`

- [ ] **Step 1: Write failing migration assertions**

Modify `tests/integration/test_migrations.py` to add `_assert_pre_live_safety_ops_schema(inspector)` after `_assert_validation_report_schema(inspector)`.

```python
def _assert_pre_live_safety_ops_schema(inspector) -> None:
    tables = set(inspector.get_table_names())
    assert {
        "execution_safety_states",
        "execution_order_intents",
        "execution_order_decisions",
        "operator_approval_requests",
        "safety_incidents",
        "kill_switch_events",
    } <= tables

    safety_columns = _columns(inspector, "execution_safety_states")
    assert {
        "id",
        "scope",
        "kill_switch_active",
        "dry_run_enabled",
        "simulated_enabled",
        "live_enabled",
        "reason",
        "updated_by",
        "updated_at",
    } <= set(safety_columns)
    assert safety_columns["scope"]["nullable"] is False
    assert safety_columns["kill_switch_active"]["nullable"] is False
    assert safety_columns["dry_run_enabled"]["nullable"] is False
    assert safety_columns["simulated_enabled"]["nullable"] is False
    assert safety_columns["live_enabled"]["nullable"] is False

    safety_indexes = _index_columns(inspector, "execution_safety_states")
    assert safety_indexes["ix_execution_safety_states_scope"] == ("scope",)
    assert safety_indexes["ix_execution_safety_states_kill_switch_active"] == (
        "kill_switch_active",
    )

    safety_uniques = _unique_columns(inspector, "execution_safety_states")
    assert safety_uniques["uq_execution_safety_states_scope"] == ("scope",)

    order_columns = _columns(inspector, "execution_order_intents")
    assert {
        "id",
        "source_type",
        "source_id",
        "paper_run_id",
        "paper_order_id",
        "client_order_id",
        "symbol",
        "instrument_id",
        "side",
        "order_type",
        "quantity",
        "limit_price",
        "estimated_price",
        "estimated_notional",
        "broker_mode",
        "status",
        "risk_profile_name",
        "risk_summary_payload",
        "approval_required",
        "approval_request_id",
        "blocked_reason_code",
        "blocked_reason",
        "created_at",
        "updated_at",
        "submitted_at",
    } <= set(order_columns)
    assert order_columns["client_order_id"]["nullable"] is False
    assert order_columns["risk_summary_payload"]["nullable"] is False

    order_indexes = _index_columns(inspector, "execution_order_intents")
    assert order_indexes["ix_execution_order_intents_client_order_id"] == (
        "client_order_id",
    )
    assert order_indexes["ix_execution_order_intents_status"] == ("status",)
    assert order_indexes["ix_execution_order_intents_broker_mode"] == ("broker_mode",)
    assert order_indexes["ix_execution_order_intents_symbol"] == ("symbol",)

    order_uniques = _unique_columns(inspector, "execution_order_intents")
    assert order_uniques["uq_execution_order_intents_client_order_id"] == (
        "client_order_id",
    )

    decision_columns = _columns(inspector, "execution_order_decisions")
    assert {
        "id",
        "order_intent_id",
        "decision_type",
        "reason_code",
        "message",
        "policy_payload",
        "created_at",
    } <= set(decision_columns)

    approval_columns = _columns(inspector, "operator_approval_requests")
    assert {
        "id",
        "resource_type",
        "resource_id",
        "status",
        "reason_code",
        "requested_by",
        "requested_at",
        "decided_by",
        "decided_at",
        "operator_note",
        "expires_at",
    } <= set(approval_columns)

    incident_columns = _columns(inspector, "safety_incidents")
    assert {
        "id",
        "severity",
        "category",
        "status",
        "resource_type",
        "resource_id",
        "reason_code",
        "message",
        "payload",
        "created_at",
        "acknowledged_by",
        "acknowledged_at",
        "resolved_by",
        "resolved_at",
    } <= set(incident_columns)

    event_columns = _columns(inspector, "kill_switch_events")
    assert {
        "id",
        "scope",
        "previous_state_payload",
        "new_state_payload",
        "operator",
        "reason",
        "created_at",
    } <= set(event_columns)
```

Call it from `test_alembic_upgrade_head_creates_runtime_schema()`:

```python
_assert_pre_live_safety_ops_schema(inspector)
```

Also assert the seeded row after migration:

```python
from sqlalchemy import text

engine = create_engine(database_url, future=True)
with engine.connect() as connection:
    row = connection.execute(
        text("select scope, kill_switch_active, dry_run_enabled, simulated_enabled, live_enabled "
             "from execution_safety_states where scope = 'global'")
    ).mappings().one()
assert row["scope"] == "global"
assert bool(row["kill_switch_active"]) is False
assert bool(row["dry_run_enabled"]) is True
assert bool(row["simulated_enabled"]) is True
assert bool(row["live_enabled"]) is False
```

- [ ] **Step 2: Run migration test to verify it fails**

Run:

```bash
pytest tests/integration/test_migrations.py::test_alembic_upgrade_head_creates_runtime_schema -q
```

Expected: FAIL because the operations tables do not exist.

- [ ] **Step 3: Write failing repository tests**

Create `tests/integration/test_operations_repositories.py`.

```python
from datetime import datetime, timedelta
from decimal import Decimal
import json

from sqlalchemy import select

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    ExecutionSafetyStateORM,
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


def _engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_safety_state_repository_seeds_global_state_and_records_kill_switch_event():
    engine = _engine()
    now = datetime(2026, 6, 26, 9, 0, 0)

    with session_scope(engine) as session:
        state_repo = ExecutionSafetyStateRepository(session)
        event_repo = KillSwitchEventRepository(session)
        state = state_repo.get_or_create_global(now=now)
        assert state.scope == "global"
        assert state.kill_switch_active is False
        assert state.dry_run_enabled is True
        assert state.simulated_enabled is True
        assert state.live_enabled is False

        previous = state_repo.payload(state)
        updated = state_repo.set_kill_switch(
            active=True,
            operator="risk lead",
            reason="pause while checking provider data",
            now=now + timedelta(minutes=1),
        )
        event = event_repo.record(
            scope="global",
            previous_state_payload=previous,
            new_state_payload=state_repo.payload(updated),
            operator="risk lead",
            reason="pause while checking provider data",
            created_at=now + timedelta(minutes=1),
        )
        event_id = event.id

    with session_scope(engine) as session:
        state = ExecutionSafetyStateRepository(session).get_global()
        event = session.get(KillSwitchEventORM, event_id)
        assert state.kill_switch_active is True
        assert state.reason == "pause while checking provider data"
        assert event.operator == "risk lead"
        assert json.loads(event.previous_state_payload)["kill_switch_active"] is False
        assert json.loads(event.new_state_payload)["kill_switch_active"] is True


def test_order_intent_repository_is_idempotent_for_matching_payload():
    engine = _engine()
    now = datetime(2026, 6, 26, 9, 0, 0)
    payload = {
        "source_type": "paper_run",
        "source_id": 7,
        "paper_run_id": 7,
        "paper_order_id": 11,
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
        "risk_profile_name": "pre_live_default",
        "risk_summary_payload": {"checks": []},
        "created_at": now,
    }

    with session_scope(engine) as session:
        repo = ExecutionOrderIntentRepository(session)
        first, created_first = repo.get_or_create(**payload)
        second, created_second = repo.get_or_create(**payload)
        assert first.id == second.id
        assert created_first is True
        assert created_second is False
        assert second.status == "created"
        assert json.loads(second.risk_summary_payload) == {"checks": []}


def test_order_intent_repository_rejects_conflicting_duplicate_client_order_id():
    engine = _engine()
    now = datetime(2026, 6, 26, 9, 0, 0)

    with session_scope(engine) as session:
        repo = ExecutionOrderIntentRepository(session)
        repo.get_or_create(
            source_type="paper_run",
            source_id=7,
            paper_run_id=7,
            paper_order_id=11,
            client_order_id="paper-7-11",
            symbol="000001",
            instrument_id=1,
            side="buy",
            order_type="market",
            quantity=100,
            limit_price=None,
            estimated_price=Decimal("10"),
            estimated_notional=Decimal("1000"),
            broker_mode="simulated",
            risk_profile_name="pre_live_default",
            risk_summary_payload={},
            created_at=now,
        )
        try:
            repo.get_or_create(
                source_type="paper_run",
                source_id=7,
                paper_run_id=7,
                paper_order_id=11,
                client_order_id="paper-7-11",
                symbol="000001",
                instrument_id=1,
                side="buy",
                order_type="market",
                quantity=200,
                limit_price=None,
                estimated_price=Decimal("10"),
                estimated_notional=Decimal("2000"),
                broker_mode="simulated",
                risk_profile_name="pre_live_default",
                risk_summary_payload={},
                created_at=now,
            )
        except ValueError as exc:
            assert str(exc) == "client_order_id already exists with different payload"
        else:
            raise AssertionError("expected conflicting duplicate client_order_id to fail")


def test_decisions_approvals_and_incidents_are_persisted_with_capped_messages():
    engine = _engine()
    now = datetime(2026, 6, 26, 9, 0, 0)

    with session_scope(engine) as session:
        order, _ = ExecutionOrderIntentRepository(session).get_or_create(
            source_type="manual_test",
            source_id=None,
            paper_run_id=None,
            paper_order_id=None,
            client_order_id="manual-1",
            symbol="000001",
            instrument_id=1,
            side="buy",
            order_type="market",
            quantity=100,
            limit_price=None,
            estimated_price=Decimal("10"),
            estimated_notional=Decimal("1000"),
            broker_mode="dry_run",
            risk_profile_name="pre_live_default",
            risk_summary_payload={},
            created_at=now,
        )
        decision = ExecutionOrderDecisionRepository(session).record(
            order_intent_id=order.id,
            decision_type="approval_required",
            reason_code="manual_approval_required_notional",
            message="x" * 2000,
            policy_payload={"estimated_notional": "1000"},
            created_at=now,
        )
        approval = OperatorApprovalRequestRepository(session).create_pending(
            resource_type="execution_order_intent",
            resource_id=order.id,
            reason_code="manual_approval_required_notional",
            requested_by="system",
            requested_at=now,
            expires_at=now + timedelta(hours=1),
        )
        incident = SafetyIncidentRepository(session).create(
            severity="warning",
            category="policy_block",
            resource_type="execution_order_intent",
            resource_id=order.id,
            reason_code="manual_approval_required_notional",
            message="y" * 3000,
            payload={"order_intent_id": order.id},
            created_at=now,
        )
        decision_id = decision.id
        approval_id = approval.id
        incident_id = incident.id

    with session_scope(engine) as session:
        decision = session.get(ExecutionOrderDecisionORM, decision_id)
        approval = session.get(OperatorApprovalRequestORM, approval_id)
        incident = session.get(SafetyIncidentORM, incident_id)
        assert len(decision.message) == 1024
        assert approval.status == "pending"
        assert approval.reason_code == "manual_approval_required_notional"
        assert len(incident.message) == 2048
        assert json.loads(incident.payload)["order_intent_id"] == order.id
```

- [ ] **Step 4: Run repository tests to verify they fail**

Run:

```bash
pytest tests/integration/test_operations_repositories.py -q
```

Expected: FAIL because ORM classes and repositories do not exist.

- [ ] **Step 5: Add ORM models**

Modify `src/quant_trading/storage/models.py`.

Add these classes after `BrokerOrderEventORM`:

```python
class ExecutionSafetyStateORM(Base):
    __tablename__ = "execution_safety_states"
    __table_args__ = (
        UniqueConstraint("scope", name="uq_execution_safety_states_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), index=True)
    kill_switch_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    dry_run_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    simulated_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    live_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(128), default="system")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ExecutionOrderIntentORM(Base):
    __tablename__ = "execution_order_intents"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_execution_order_intents_client_order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    paper_run_id: Mapped[int | None] = mapped_column(ForeignKey("paper_runs.id"), nullable=True, index=True)
    paper_order_id: Mapped[int | None] = mapped_column(ForeignKey("paper_orders.id"), nullable=True, index=True)
    client_order_id: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    side: Mapped[str] = mapped_column(String(16))
    order_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    estimated_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    estimated_notional: Mapped[float] = mapped_column(Numeric(24, 6), default=0)
    broker_mode: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    risk_profile_name: Mapped[str] = mapped_column(String(128), index=True)
    risk_summary_payload: Mapped[str] = mapped_column(Text, default="{}")
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approval_request_id: Mapped[int | None] = mapped_column(ForeignKey("operator_approval_requests.id"), nullable=True, index=True)
    blocked_reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class ExecutionOrderDecisionORM(Base):
    __tablename__ = "execution_order_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_intent_id: Mapped[int] = mapped_column(ForeignKey("execution_order_intents.id"), index=True)
    decision_type: Mapped[str] = mapped_column(String(32), index=True)
    reason_code: Mapped[str] = mapped_column(String(128), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    policy_payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class OperatorApprovalRequestORM(Base):
    __tablename__ = "operator_approval_requests"
    __table_args__ = (
        Index(
            "ix_operator_approval_requests_resource",
            "resource_type",
            "resource_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    reason_code: Mapped[str] = mapped_column(String(128), index=True)
    requested_by: Mapped[str] = mapped_column(String(128), default="system")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    operator_note: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class SafetyIncidentORM(Base):
    __tablename__ = "safety_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reason_code: Mapped[str] = mapped_column(String(128), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KillSwitchEventORM(Base):
    __tablename__ = "kill_switch_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), index=True)
    previous_state_payload: Mapped[str] = mapped_column(Text, default="{}")
    new_state_payload: Mapped[str] = mapped_column(Text, default="{}")
    operator: Mapped[str] = mapped_column(String(128), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
```

- [ ] **Step 6: Add repositories**

Modify imports in `src/quant_trading/storage/repositories.py`:

```python
from quant_trading.storage.models import (
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    ExecutionSafetyStateORM,
    KillSwitchEventORM,
    OperatorApprovalRequestORM,
    SafetyIncidentORM,
)
```

Add helpers near `_json_dumps`:

```python
def _cap_text(value: str, limit: int) -> str:
    return str(value or "")[:limit]
```

Add repository classes after `BrokerOrderEventRepository`:

```python
class ExecutionSafetyStateRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_global(self) -> ExecutionSafetyStateORM | None:
        return self.session.scalar(
            select(ExecutionSafetyStateORM).where(ExecutionSafetyStateORM.scope == "global")
        )

    def get_or_create_global(self, *, now: datetime) -> ExecutionSafetyStateORM:
        row = self.get_global()
        if row is not None:
            return row
        row = ExecutionSafetyStateORM(
            scope="global",
            kill_switch_active=False,
            dry_run_enabled=True,
            simulated_enabled=True,
            live_enabled=False,
            reason="default simulated and dry-run startup",
            updated_by="system",
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def set_kill_switch(
        self,
        *,
        active: bool,
        operator: str,
        reason: str,
        now: datetime,
    ) -> ExecutionSafetyStateORM:
        row = self.get_or_create_global(now=now)
        row.kill_switch_active = active
        row.reason = _cap_text(reason, 1024)
        row.updated_by = _cap_text(operator, 128)
        row.updated_at = now
        self.session.flush()
        return row

    def payload(self, row: ExecutionSafetyStateORM) -> dict:
        return {
            "scope": row.scope,
            "kill_switch_active": row.kill_switch_active,
            "dry_run_enabled": row.dry_run_enabled,
            "simulated_enabled": row.simulated_enabled,
            "live_enabled": row.live_enabled,
            "reason": row.reason,
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat(),
        }
```

```python
class ExecutionOrderIntentRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, order_intent_id: int) -> ExecutionOrderIntentORM | None:
        return self.session.get(ExecutionOrderIntentORM, order_intent_id)

    def get_by_client_order_id(self, client_order_id: str) -> ExecutionOrderIntentORM | None:
        return self.session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == client_order_id
            )
        )

    def get_or_create(
        self,
        *,
        source_type: str,
        source_id: int | None,
        paper_run_id: int | None,
        paper_order_id: int | None,
        client_order_id: str,
        symbol: str,
        instrument_id: int,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: Decimal | None,
        estimated_price: Decimal | None,
        estimated_notional: Decimal,
        broker_mode: str,
        risk_profile_name: str,
        risk_summary_payload: dict,
        created_at: datetime,
    ) -> tuple[ExecutionOrderIntentORM, bool]:
        existing = self.get_by_client_order_id(client_order_id)
        payload = _json_dumps(risk_summary_payload)
        if existing is not None:
            comparable = {
                "source_type": existing.source_type,
                "source_id": existing.source_id,
                "paper_run_id": existing.paper_run_id,
                "paper_order_id": existing.paper_order_id,
                "symbol": existing.symbol,
                "instrument_id": existing.instrument_id,
                "side": existing.side,
                "order_type": existing.order_type,
                "quantity": existing.quantity,
                "limit_price": existing.limit_price,
                "estimated_price": existing.estimated_price,
                "estimated_notional": existing.estimated_notional,
                "broker_mode": existing.broker_mode,
                "risk_profile_name": existing.risk_profile_name,
                "risk_summary_payload": existing.risk_summary_payload,
            }
            incoming = {
                "source_type": source_type,
                "source_id": source_id,
                "paper_run_id": paper_run_id,
                "paper_order_id": paper_order_id,
                "symbol": symbol,
                "instrument_id": instrument_id,
                "side": side,
                "order_type": order_type,
                "quantity": quantity,
                "limit_price": limit_price,
                "estimated_price": estimated_price,
                "estimated_notional": estimated_notional,
                "broker_mode": broker_mode,
                "risk_profile_name": risk_profile_name,
                "risk_summary_payload": payload,
            }
            if comparable != incoming:
                raise ValueError("client_order_id already exists with different payload")
            return existing, False
        row = ExecutionOrderIntentORM(
            source_type=source_type,
            source_id=source_id,
            paper_run_id=paper_run_id,
            paper_order_id=paper_order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            instrument_id=instrument_id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            estimated_price=estimated_price,
            estimated_notional=estimated_notional,
            broker_mode=broker_mode,
            status="created",
            risk_profile_name=risk_profile_name,
            risk_summary_payload=payload,
            approval_required=False,
            created_at=created_at,
            updated_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row, True

    def set_status(
        self,
        row: ExecutionOrderIntentORM,
        *,
        status: str,
        updated_at: datetime,
        approval_required: bool | None = None,
        approval_request_id: int | None = None,
        blocked_reason_code: str | None = None,
        blocked_reason: str | None = None,
        submitted_at: datetime | None = None,
    ) -> ExecutionOrderIntentORM:
        row.status = status
        row.updated_at = updated_at
        if approval_required is not None:
            row.approval_required = approval_required
        if approval_request_id is not None:
            row.approval_request_id = approval_request_id
        if blocked_reason_code is not None:
            row.blocked_reason_code = blocked_reason_code
        if blocked_reason is not None:
            row.blocked_reason = _cap_text(blocked_reason, 1024)
        if submitted_at is not None:
            row.submitted_at = submitted_at
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        status: str | None = None,
        broker_mode: str | None = None,
        limit: int = 50,
    ) -> list[ExecutionOrderIntentORM]:
        statement = select(ExecutionOrderIntentORM).order_by(
            ExecutionOrderIntentORM.id.desc()
        ).limit(limit)
        if status:
            statement = statement.where(ExecutionOrderIntentORM.status == status)
        if broker_mode:
            statement = statement.where(ExecutionOrderIntentORM.broker_mode == broker_mode)
        return list(self.session.scalars(statement).all())
```

```python
class ExecutionOrderDecisionRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        order_intent_id: int,
        decision_type: str,
        reason_code: str,
        message: str,
        policy_payload: dict,
        created_at: datetime,
    ) -> ExecutionOrderDecisionORM:
        row = ExecutionOrderDecisionORM(
            order_intent_id=order_intent_id,
            decision_type=decision_type,
            reason_code=reason_code,
            message=_cap_text(message, 1024),
            policy_payload=_json_dumps(policy_payload),
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_recent(self, *, limit: int = 50) -> list[ExecutionOrderDecisionORM]:
        return list(
            self.session.scalars(
                select(ExecutionOrderDecisionORM)
                .order_by(ExecutionOrderDecisionORM.id.desc())
                .limit(limit)
            ).all()
        )
```

```python
class OperatorApprovalRequestRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, approval_request_id: int) -> OperatorApprovalRequestORM | None:
        return self.session.get(OperatorApprovalRequestORM, approval_request_id)

    def get_active_for_resource(
        self,
        *,
        resource_type: str,
        resource_id: int,
    ) -> OperatorApprovalRequestORM | None:
        return self.session.scalar(
            select(OperatorApprovalRequestORM)
            .where(OperatorApprovalRequestORM.resource_type == resource_type)
            .where(OperatorApprovalRequestORM.resource_id == resource_id)
            .where(OperatorApprovalRequestORM.status == "pending")
        )

    def create_pending(
        self,
        *,
        resource_type: str,
        resource_id: int,
        reason_code: str,
        requested_by: str,
        requested_at: datetime,
        expires_at: datetime | None,
    ) -> OperatorApprovalRequestORM:
        existing = self.get_active_for_resource(
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if existing is not None:
            return existing
        row = OperatorApprovalRequestORM(
            resource_type=resource_type,
            resource_id=resource_id,
            status="pending",
            reason_code=reason_code,
            requested_by=_cap_text(requested_by, 128),
            requested_at=requested_at,
            expires_at=expires_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def decide(
        self,
        row: OperatorApprovalRequestORM,
        *,
        status: str,
        operator: str,
        note: str,
        decided_at: datetime,
    ) -> OperatorApprovalRequestORM:
        if row.status != "pending":
            raise ValueError("approval request is not pending")
        row.status = status
        row.decided_by = _cap_text(operator, 128)
        row.operator_note = _cap_text(note, 2048)
        row.decided_at = decided_at
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[OperatorApprovalRequestORM]:
        statement = select(OperatorApprovalRequestORM).order_by(
            OperatorApprovalRequestORM.id.desc()
        ).limit(limit)
        if status:
            statement = statement.where(OperatorApprovalRequestORM.status == status)
        return list(self.session.scalars(statement).all())
```

```python
class SafetyIncidentRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, incident_id: int) -> SafetyIncidentORM | None:
        return self.session.get(SafetyIncidentORM, incident_id)

    def create(
        self,
        *,
        severity: str,
        category: str,
        resource_type: str | None,
        resource_id: int | None,
        reason_code: str,
        message: str,
        payload: dict,
        created_at: datetime,
    ) -> SafetyIncidentORM:
        row = SafetyIncidentORM(
            severity=severity,
            category=category,
            status="open",
            resource_type=resource_type,
            resource_id=resource_id,
            reason_code=reason_code,
            message=_cap_text(message, 2048),
            payload=_json_dumps(payload),
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def acknowledge(
        self,
        row: SafetyIncidentORM,
        *,
        operator: str,
        acknowledged_at: datetime,
    ) -> SafetyIncidentORM:
        if row.status == "resolved":
            raise ValueError("incident is already resolved")
        row.status = "acknowledged"
        row.acknowledged_by = _cap_text(operator, 128)
        row.acknowledged_at = acknowledged_at
        self.session.flush()
        return row

    def resolve(
        self,
        row: SafetyIncidentORM,
        *,
        operator: str,
        resolved_at: datetime,
    ) -> SafetyIncidentORM:
        row.status = "resolved"
        row.resolved_by = _cap_text(operator, 128)
        row.resolved_at = resolved_at
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[SafetyIncidentORM]:
        statement = select(SafetyIncidentORM).order_by(SafetyIncidentORM.id.desc()).limit(limit)
        if status:
            statement = statement.where(SafetyIncidentORM.status == status)
        if severity:
            statement = statement.where(SafetyIncidentORM.severity == severity)
        return list(self.session.scalars(statement).all())
```

```python
class KillSwitchEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        scope: str,
        previous_state_payload: dict,
        new_state_payload: dict,
        operator: str,
        reason: str,
        created_at: datetime,
    ) -> KillSwitchEventORM:
        row = KillSwitchEventORM(
            scope=scope,
            previous_state_payload=_json_dumps(previous_state_payload),
            new_state_payload=_json_dumps(new_state_payload),
            operator=_cap_text(operator, 128),
            reason=_cap_text(reason, 1024),
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_recent(self, *, limit: int = 50) -> list[KillSwitchEventORM]:
        return list(
            self.session.scalars(
                select(KillSwitchEventORM)
                .order_by(KillSwitchEventORM.id.desc())
                .limit(limit)
            ).all()
        )
```

- [ ] **Step 7: Add Alembic migration**

Create `migrations/versions/20260626_0010_add_pre_live_safety_ops.py`.

```python
"""add pre live safety ops

Revision ID: 20260626_0010
Revises: 20260626_0009
Create Date: 2026-06-26 00:10:00.000000
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_0010"
down_revision: str | None = "20260626_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_safety_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("kill_switch_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dry_run_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("simulated_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("live_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("scope", name="uq_execution_safety_states_scope"),
    )
    op.create_index(op.f("ix_execution_safety_states_scope"), "execution_safety_states", ["scope"])
    op.create_index(op.f("ix_execution_safety_states_kill_switch_active"), "execution_safety_states", ["kill_switch_active"])
    op.create_index(op.f("ix_execution_safety_states_dry_run_enabled"), "execution_safety_states", ["dry_run_enabled"])
    op.create_index(op.f("ix_execution_safety_states_simulated_enabled"), "execution_safety_states", ["simulated_enabled"])
    op.create_index(op.f("ix_execution_safety_states_live_enabled"), "execution_safety_states", ["live_enabled"])
    op.create_index(op.f("ix_execution_safety_states_updated_at"), "execution_safety_states", ["updated_at"])

    op.create_table(
        "operator_approval_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("operator_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    for column in ["resource_type", "resource_id", "status", "reason_code", "requested_at", "decided_at", "expires_at"]:
        op.create_index(op.f(f"ix_operator_approval_requests_{column}"), "operator_approval_requests", [column])
    op.create_index("ix_operator_approval_requests_resource", "operator_approval_requests", ["resource_type", "resource_id"])

    op.create_table(
        "execution_order_intents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("paper_run_id", sa.Integer(), sa.ForeignKey("paper_runs.id"), nullable=True),
        sa.Column("paper_order_id", sa.Integer(), sa.ForeignKey("paper_orders.id"), nullable=True),
        sa.Column("client_order_id", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("estimated_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("estimated_notional", sa.Numeric(24, 6), nullable=False, server_default="0"),
        sa.Column("broker_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("risk_profile_name", sa.String(length=128), nullable=False),
        sa.Column("risk_summary_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_request_id", sa.Integer(), sa.ForeignKey("operator_approval_requests.id"), nullable=True),
        sa.Column("blocked_reason_code", sa.String(length=128), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_order_id", name="uq_execution_order_intents_client_order_id"),
    )
    for column in [
        "source_type", "source_id", "paper_run_id", "paper_order_id", "client_order_id",
        "symbol", "instrument_id", "broker_mode", "status", "risk_profile_name",
        "approval_required", "approval_request_id", "blocked_reason_code", "created_at",
        "updated_at", "submitted_at",
    ]:
        op.create_index(op.f(f"ix_execution_order_intents_{column}"), "execution_order_intents", [column])

    op.create_table(
        "execution_order_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_intent_id", sa.Integer(), sa.ForeignKey("execution_order_intents.id"), nullable=False),
        sa.Column("decision_type", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("policy_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ["order_intent_id", "decision_type", "reason_code", "created_at"]:
        op.create_index(op.f(f"ix_execution_order_decisions_{column}"), "execution_order_decisions", [column])

    op.create_table(
        "safety_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    for column in ["severity", "category", "status", "resource_type", "resource_id", "reason_code", "created_at"]:
        op.create_index(op.f(f"ix_safety_incidents_{column}"), "safety_incidents", [column])

    op.create_table(
        "kill_switch_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("previous_state_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("new_state_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("operator", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(op.f("ix_kill_switch_events_scope"), "kill_switch_events", ["scope"])
    op.create_index(op.f("ix_kill_switch_events_created_at"), "kill_switch_events", ["created_at"])

    safety_table = sa.table(
        "execution_safety_states",
        sa.column("scope", sa.String),
        sa.column("kill_switch_active", sa.Boolean),
        sa.column("dry_run_enabled", sa.Boolean),
        sa.column("simulated_enabled", sa.Boolean),
        sa.column("live_enabled", sa.Boolean),
        sa.column("reason", sa.Text),
        sa.column("updated_by", sa.String),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        safety_table,
        [
            {
                "scope": "global",
                "kill_switch_active": False,
                "dry_run_enabled": True,
                "simulated_enabled": True,
                "live_enabled": False,
                "reason": "default simulated and dry-run startup",
                "updated_by": "system",
                "updated_at": datetime.utcnow(),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("kill_switch_events")
    op.drop_table("safety_incidents")
    op.drop_table("execution_order_decisions")
    op.drop_table("execution_order_intents")
    op.drop_table("operator_approval_requests")
    op.drop_table("execution_safety_states")
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
pytest tests/integration/test_migrations.py::test_alembic_upgrade_head_creates_runtime_schema tests/integration/test_operations_repositories.py -q
```

Expected: PASS.

- [ ] **Step 9: Run storage regression tests**

Run:

```bash
pytest tests/integration/test_broker_order_events_repository.py tests/integration/test_paper_storage_models.py tests/integration/test_storage_repositories.py -q
```

Expected: PASS.

- [ ] **Step 10: Spec review**

Check:

- The six tables from the spec exist.
- The global safety state seed uses `kill_switch_active=false`, `dry_run_enabled=true`, `simulated_enabled=true`, and `live_enabled=false`.
- Repository methods cap messages and payloads before persistence.
- No broker SDK, live mode, or execution path was added.

Record:

```text
Spec review Task 1: PASS - storage, migration, default safety state, and audit repositories match the pre-live safety ops spec; no live execution behavior added.
```

- [ ] **Step 11: Quality review**

Check:

- Alembic downgrade drops child tables before parent tables.
- JSON serialization handles `Decimal`, `date`, and enum values through existing `_json_dumps`.
- `client_order_id` uniqueness is enforced by both repository and DB constraint.
- Repository methods do not silently mutate broker/paper state.

Record:

```text
Quality review Task 1: PASS - storage names are explicit, payloads are bounded, migration is reversible, and repository behavior is transaction-scoped.
```

- [ ] **Step 12: Commit**

Run:

```bash
git add src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260626_0010_add_pre_live_safety_ops.py tests/integration/test_migrations.py tests/integration/test_operations_repositories.py
git commit -m "feat: add pre-live safety storage"
```

---

### Task 2: Pre-Live Safety Policy Service

**Files:**
- Create: `src/quant_trading/operations/__init__.py`
- Create: `src/quant_trading/operations/safety.py`
- Create: `tests/unit/test_operations_safety.py`
- Create: `tests/integration/test_operations_safety_service.py`

- [ ] **Step 1: Write failing unit tests for policy and state transitions**

Create `tests/unit/test_operations_safety.py`.

```python
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from quant_trading.core.enums import Market, OrderSide
from quant_trading.core.models import Bar, OrderIntent, Portfolio, Position
from quant_trading.execution.broker import BrokerExecutionMode
from quant_trading.operations.safety import (
    ExecutionOrderStateMachine,
    PreLiveRiskProfile,
    PreLiveSafetyService,
    SafetyPolicyInput,
)


def _bar(timestamp=date(2026, 6, 26), close="10"):
    return Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=timestamp,
        open=Decimal(close),
        high=Decimal(close) + Decimal("1"),
        low=Decimal(close) - Decimal("1"),
        close=Decimal(close),
        volume=Decimal("100000"),
    )


def _portfolio(cash="100000", quantity=0, market_price="10", peak_equity=None):
    positions = {}
    if quantity:
        positions[1] = Position(
            instrument_id=1,
            symbol="000001",
            quantity=quantity,
            avg_cost=Decimal("8"),
            market_price=Decimal(market_price),
        )
    return Portfolio(
        account_id=1,
        cash=Decimal(cash),
        positions=positions,
        peak_equity=Decimal(peak_equity) if peak_equity is not None else None,
    )


def _intent(side=OrderSide.BUY, quantity=100):
    return OrderIntent(
        instrument_id=1,
        symbol="000001",
        side=side,
        quantity=quantity,
        reason="unit-test",
    )


def test_default_profile_values_are_pre_live_safe():
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


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        ("created", "risk_approved", True),
        ("created", "approval_required", True),
        ("created", "blocked", True),
        ("approval_required", "operator_approved", True),
        ("risk_approved", "submitted", True),
        ("submitted", "risk_approved", False),
        ("blocked", "submitted", False),
    ],
)
def test_order_state_machine_allows_only_specified_transitions(current, target, allowed):
    if allowed:
        ExecutionOrderStateMachine.validate(current, target)
    else:
        with pytest.raises(ValueError, match="invalid execution order transition"):
            ExecutionOrderStateMachine.validate(current, target)


def test_policy_blocks_when_global_kill_switch_is_active():
    decision = PreLiveSafetyService.evaluate_policy(
        SafetyPolicyInput(
            intent=_intent(),
            latest_bar=_bar(),
            portfolio=_portfolio(),
            broker_mode=BrokerExecutionMode.SIMULATED,
            profile=PreLiveRiskProfile.default(),
            kill_switch_active=True,
            broker_mode_enabled=True,
            live_enabled=False,
            daily_turnover=Decimal("0"),
            daily_order_count=0,
            now=datetime(2026, 6, 26, 9, 0, 0),
        )
    )

    assert decision.decision_type == "blocked"
    assert decision.reason_code == "blocked_global_kill_switch"
    assert decision.broker_submission_allowed is False


def test_policy_requires_approval_above_manual_notional_threshold():
    decision = PreLiveSafetyService.evaluate_policy(
        SafetyPolicyInput(
            intent=_intent(quantity=6000),
            latest_bar=_bar(close="10"),
            portfolio=_portfolio(),
            broker_mode=BrokerExecutionMode.SIMULATED,
            profile=PreLiveRiskProfile.default(),
            kill_switch_active=False,
            broker_mode_enabled=True,
            live_enabled=False,
            daily_turnover=Decimal("0"),
            daily_order_count=0,
            now=datetime(2026, 6, 26, 9, 0, 0),
        )
    )

    assert decision.decision_type == "approval_required"
    assert decision.reason_code == "manual_approval_required_notional"
    assert decision.broker_submission_allowed is False


def test_policy_requires_approval_for_sell_without_position():
    decision = PreLiveSafetyService.evaluate_policy(
        SafetyPolicyInput(
            intent=_intent(side=OrderSide.SELL, quantity=100),
            latest_bar=_bar(close="10"),
            portfolio=_portfolio(quantity=0),
            broker_mode=BrokerExecutionMode.DRY_RUN,
            profile=PreLiveRiskProfile.default(),
            kill_switch_active=False,
            broker_mode_enabled=True,
            live_enabled=False,
            daily_turnover=Decimal("0"),
            daily_order_count=0,
            now=datetime(2026, 6, 26, 9, 0, 0),
        )
    )

    assert decision.decision_type == "approval_required"
    assert decision.reason_code == "manual_approval_required_sell_without_position"
    assert decision.broker_submission_allowed is False


def test_policy_blocks_live_mode_even_if_trading_flag_is_true():
    decision = PreLiveSafetyService.evaluate_policy(
        SafetyPolicyInput(
            intent=_intent(),
            latest_bar=_bar(close="10"),
            portfolio=_portfolio(),
            broker_mode=BrokerExecutionMode.LIVE,
            profile=PreLiveRiskProfile.default(),
            kill_switch_active=False,
            broker_mode_enabled=False,
            live_enabled=True,
            daily_turnover=Decimal("0"),
            daily_order_count=0,
            now=datetime(2026, 6, 26, 9, 0, 0),
        )
    )

    assert decision.decision_type == "blocked"
    assert decision.reason_code == "blocked_live_mode_unavailable"
    assert decision.broker_submission_allowed is False


def test_policy_approves_simulated_order_when_all_checks_pass():
    decision = PreLiveSafetyService.evaluate_policy(
        SafetyPolicyInput(
            intent=_intent(quantity=100),
            latest_bar=_bar(close="10"),
            portfolio=_portfolio(),
            broker_mode=BrokerExecutionMode.SIMULATED,
            profile=PreLiveRiskProfile.default(),
            kill_switch_active=False,
            broker_mode_enabled=True,
            live_enabled=False,
            daily_turnover=Decimal("0"),
            daily_order_count=0,
            now=datetime(2026, 6, 26, 9, 0, 0),
        )
    )

    assert decision.decision_type == "approved"
    assert decision.reason_code == "approved"
    assert decision.broker_submission_allowed is True
```

- [ ] **Step 2: Run unit tests to verify they fail**

Run:

```bash
pytest tests/unit/test_operations_safety.py -q
```

Expected: FAIL because `quant_trading.operations.safety` does not exist.

- [ ] **Step 3: Write failing integration tests for persisted service decisions**

Create `tests/integration/test_operations_safety_service.py`.

```python
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from quant_trading.core.enums import Market, OrderSide
from quant_trading.core.models import Bar, OrderIntent, Portfolio
from quant_trading.execution.broker import BrokerExecutionMode
from quant_trading.operations.safety import PreLiveSafetyService
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    OperatorApprovalRequestORM,
)
from quant_trading.storage.repositories import ExecutionSafetyStateRepository


def _engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def _bar(close="10"):
    return Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=date(2026, 6, 26),
        open=Decimal(close),
        high=Decimal(close) + Decimal("1"),
        low=Decimal(close) - Decimal("1"),
        close=Decimal(close),
        volume=Decimal("100000"),
    )


def _portfolio():
    return Portfolio(account_id=1, cash=Decimal("100000"))


def _intent(quantity=100, side=OrderSide.BUY):
    return OrderIntent(
        instrument_id=1,
        symbol="000001",
        side=side,
        quantity=quantity,
        reason="integration-test",
    )


def test_safety_service_persists_approved_decision_and_order_intent():
    engine = _engine()
    now = datetime(2026, 6, 26, 9, 0, 0)

    with session_scope(engine) as session:
        decision = PreLiveSafetyService(session).evaluate_order_intent(
            intent=_intent(quantity=100),
            latest_bar=_bar(close="10"),
            portfolio=_portfolio(),
            broker_mode=BrokerExecutionMode.SIMULATED,
            source_type="paper_run",
            source_id=3,
            paper_run_id=3,
            paper_order_id=5,
            client_order_id="paper-3-5",
            now=now,
        )
        assert decision.decision_type == "approved"
        assert decision.reason_code == "approved"
        assert decision.broker_submission_allowed is True

    with session_scope(engine) as session:
        order = session.scalar(select(ExecutionOrderIntentORM))
        decisions = session.scalars(select(ExecutionOrderDecisionORM)).all()
        assert order.client_order_id == "paper-3-5"
        assert order.status == "risk_approved"
        assert order.approval_required is False
        assert len(decisions) == 1
        assert decisions[0].decision_type == "approved"


def test_safety_service_blocks_when_kill_switch_active_and_creates_no_approval():
    engine = _engine()
    now = datetime(2026, 6, 26, 9, 0, 0)

    with session_scope(engine) as session:
        ExecutionSafetyStateRepository(session).set_kill_switch(
            active=True,
            operator="risk",
            reason="manual pause",
            now=now,
        )
        decision = PreLiveSafetyService(session).evaluate_order_intent(
            intent=_intent(quantity=100),
            latest_bar=_bar(close="10"),
            portfolio=_portfolio(),
            broker_mode=BrokerExecutionMode.SIMULATED,
            source_type="paper_run",
            source_id=3,
            paper_run_id=3,
            paper_order_id=5,
            client_order_id="paper-3-5",
            now=now,
        )
        assert decision.decision_type == "blocked"
        assert decision.reason_code == "blocked_global_kill_switch"
        assert decision.broker_submission_allowed is False

    with session_scope(engine) as session:
        order = session.scalar(select(ExecutionOrderIntentORM))
        approvals = session.scalars(select(OperatorApprovalRequestORM)).all()
        assert order.status == "blocked"
        assert order.blocked_reason_code == "blocked_global_kill_switch"
        assert approvals == []


def test_safety_service_creates_and_approves_operator_request():
    engine = _engine()
    now = datetime(2026, 6, 26, 9, 0, 0)

    with session_scope(engine) as session:
        service = PreLiveSafetyService(session)
        decision = service.evaluate_order_intent(
            intent=_intent(quantity=6000),
            latest_bar=_bar(close="10"),
            portfolio=_portfolio(),
            broker_mode=BrokerExecutionMode.SIMULATED,
            source_type="paper_run",
            source_id=3,
            paper_run_id=3,
            paper_order_id=5,
            client_order_id="paper-3-5",
            now=now,
        )
        approved = service.approve_order_intent(
            decision.order_intent_id,
            operator="risk lead",
            note="approved for dry-run rehearsal",
            now=now,
        )
        assert decision.decision_type == "approval_required"
        assert decision.approval_request_id is not None
        assert approved.decision_type == "approved"
        assert approved.reason_code == "approved"

    with session_scope(engine) as session:
        order = session.scalar(select(ExecutionOrderIntentORM))
        approval = session.scalar(select(OperatorApprovalRequestORM))
        assert order.status == "operator_approved"
        assert order.approval_required is True
        assert approval.status == "approved"
        assert approval.decided_by == "risk lead"
```

- [ ] **Step 4: Run integration tests to verify they fail**

Run:

```bash
pytest tests/integration/test_operations_safety_service.py -q
```

Expected: FAIL because `PreLiveSafetyService` does not exist.

- [ ] **Step 5: Add operations package exports**

Create `src/quant_trading/operations/__init__.py`.

```python
from quant_trading.operations.safety import (
    ExecutionOrderStateMachine,
    PreLiveRiskProfile,
    PreLiveSafetyDecision,
    PreLiveSafetyService,
    SafetyPolicyInput,
)

__all__ = [
    "ExecutionOrderStateMachine",
    "PreLiveRiskProfile",
    "PreLiveSafetyDecision",
    "PreLiveSafetyService",
    "SafetyPolicyInput",
]
```

- [ ] **Step 6: Implement safety policy and service**

Create `src/quant_trading/operations/safety.py`.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_trading.core.enums import OrderSide
from quant_trading.core.models import Bar, OrderIntent, Portfolio
from quant_trading.execution.broker import BrokerExecutionMode
from quant_trading.storage.models import ExecutionOrderIntentORM
from quant_trading.storage.repositories import (
    ExecutionOrderDecisionRepository,
    ExecutionOrderIntentRepository,
    ExecutionSafetyStateRepository,
    OperatorApprovalRequestRepository,
)


APPROVAL_RESOURCE_TYPE = "execution_order_intent"


@dataclass(frozen=True)
class PreLiveRiskProfile:
    name: str
    max_single_order_notional: Decimal
    max_gross_exposure_ratio: Decimal
    max_daily_turnover: Decimal
    max_daily_order_count: int
    max_drawdown_stop_ratio: Decimal
    stale_data_max_age_days: int
    manual_approval_notional: Decimal
    manual_approval_sell_without_position: bool
    allowed_broker_modes: set[str] = field(default_factory=set)

    @classmethod
    def default(cls) -> "PreLiveRiskProfile":
        return cls(
            name="pre_live_default",
            max_single_order_notional=Decimal("100000"),
            max_gross_exposure_ratio=Decimal("1.0"),
            max_daily_turnover=Decimal("300000"),
            max_daily_order_count=20,
            max_drawdown_stop_ratio=Decimal("0.10"),
            stale_data_max_age_days=10,
            manual_approval_notional=Decimal("50000"),
            manual_approval_sell_without_position=True,
            allowed_broker_modes={"simulated", "dry_run"},
        )


@dataclass(frozen=True)
class SafetyPolicyInput:
    intent: OrderIntent
    latest_bar: Bar | None
    portfolio: Portfolio
    broker_mode: BrokerExecutionMode | str
    profile: PreLiveRiskProfile
    kill_switch_active: bool
    broker_mode_enabled: bool
    live_enabled: bool
    daily_turnover: Decimal
    daily_order_count: int
    now: datetime


@dataclass(frozen=True)
class PreLiveSafetyDecision:
    order_intent_id: int
    decision_type: str
    reason_code: str
    message: str
    broker_submission_allowed: bool
    approval_request_id: int | None = None


@dataclass(frozen=True)
class PolicyDecision:
    decision_type: str
    reason_code: str
    message: str
    broker_submission_allowed: bool
    policy_payload: dict


class ExecutionOrderStateMachine:
    _allowed = {
        "created": {"risk_approved", "approval_required", "blocked", "cancelled"},
        "approval_required": {"operator_approved", "blocked", "cancelled"},
        "risk_approved": {"submitted", "skipped", "cancelled"},
        "operator_approved": {"submitted", "skipped"},
    }

    @classmethod
    def validate(cls, current: str, target: str) -> None:
        if target not in cls._allowed.get(current, set()):
            raise ValueError(f"invalid execution order transition: {current} -> {target}")


class PreLiveSafetyService:
    def __init__(self, session: Session, profile: PreLiveRiskProfile | None = None):
        self.session = session
        self.profile = profile or PreLiveRiskProfile.default()

    @staticmethod
    def evaluate_policy(input: SafetyPolicyInput) -> PolicyDecision:
        profile = input.profile
        mode = BrokerExecutionMode(input.broker_mode)
        latest_bar = input.latest_bar
        estimated_notional = Decimal("0")
        if latest_bar is not None:
            estimated_notional = latest_bar.close * Decimal(input.intent.quantity)
        payload = {
            "broker_mode": mode.value,
            "estimated_notional": str(estimated_notional),
            "daily_turnover": str(input.daily_turnover),
            "daily_order_count": input.daily_order_count,
            "portfolio_equity": str(input.portfolio.equity),
            "portfolio_drawdown": str(input.portfolio.drawdown),
        }

        if mode is BrokerExecutionMode.LIVE:
            return PolicyDecision(
                "blocked",
                "blocked_live_mode_unavailable",
                "live broker mode is unavailable in this milestone",
                False,
                payload,
            )
        if input.kill_switch_active:
            return PolicyDecision(
                "blocked",
                "blocked_global_kill_switch",
                "global kill switch is active",
                False,
                payload,
            )
        if mode.value not in profile.allowed_broker_modes or not input.broker_mode_enabled:
            return PolicyDecision(
                "blocked",
                "blocked_broker_mode_disabled",
                "broker mode is disabled by safety profile or runtime state",
                False,
                payload,
            )
        if latest_bar is None:
            return PolicyDecision("blocked", "blocked_stale_market_data", "market data is missing", False, payload)
        if latest_bar.close <= 0:
            return PolicyDecision("blocked", "blocked_invalid_price", "latest close price is invalid", False, payload)
        if isinstance(latest_bar.timestamp, datetime):
            bar_date = latest_bar.timestamp.date()
        elif isinstance(latest_bar.timestamp, date):
            bar_date = latest_bar.timestamp
        else:
            bar_date = date.fromisoformat(str(latest_bar.timestamp))
        age_days = (input.now.date() - bar_date).days
        if age_days > profile.stale_data_max_age_days:
            payload["data_age_days"] = age_days
            return PolicyDecision("blocked", "blocked_stale_market_data", "market data is stale", False, payload)
        if estimated_notional > profile.max_single_order_notional:
            return PolicyDecision(
                "blocked",
                "blocked_max_single_order_notional",
                "single order notional exceeds pre-live limit",
                False,
                payload,
            )
        if input.daily_turnover + estimated_notional > profile.max_daily_turnover:
            return PolicyDecision("blocked", "blocked_max_daily_turnover", "daily turnover exceeds pre-live limit", False, payload)
        if input.daily_order_count >= profile.max_daily_order_count:
            return PolicyDecision("blocked", "blocked_max_daily_order_count", "daily order count exceeds pre-live limit", False, payload)
        if input.portfolio.drawdown > profile.max_drawdown_stop_ratio:
            return PolicyDecision("blocked", "blocked_drawdown_stop", "portfolio drawdown exceeds stop threshold", False, payload)
        if input.portfolio.equity <= 0:
            return PolicyDecision("blocked", "blocked_max_gross_exposure", "portfolio equity must be positive", False, payload)
        proposed_market_value = input.portfolio.market_value
        if input.intent.side is OrderSide.BUY:
            proposed_market_value += estimated_notional
        else:
            existing_position = input.portfolio.positions.get(input.intent.instrument_id)
            if existing_position is None and profile.manual_approval_sell_without_position:
                return PolicyDecision(
                    "approval_required",
                    "manual_approval_required_sell_without_position",
                    "sell order without an existing position requires operator approval",
                    False,
                    payload,
                )
            existing_value = existing_position.market_value if existing_position is not None else Decimal("0")
            proposed_market_value -= min(existing_value, estimated_notional)
        proposed_exposure = proposed_market_value / input.portfolio.equity
        payload["proposed_gross_exposure_ratio"] = str(proposed_exposure)
        if proposed_exposure > profile.max_gross_exposure_ratio:
            return PolicyDecision("blocked", "blocked_max_gross_exposure", "gross exposure exceeds pre-live limit", False, payload)
        if estimated_notional > profile.manual_approval_notional:
            return PolicyDecision(
                "approval_required",
                "manual_approval_required_notional",
                "order notional requires operator approval",
                False,
                payload,
            )
        return PolicyDecision("approved", "approved", "pre-live safety policy approved", True, payload)

    def evaluate_order_intent(
        self,
        *,
        intent: OrderIntent,
        latest_bar: Bar | None,
        portfolio: Portfolio,
        broker_mode: BrokerExecutionMode | str,
        source_type: str,
        source_id: int | None,
        paper_run_id: int | None,
        paper_order_id: int | None,
        client_order_id: str,
        now: datetime,
    ) -> PreLiveSafetyDecision:
        mode = BrokerExecutionMode(broker_mode)
        state_repo = ExecutionSafetyStateRepository(self.session)
        state = state_repo.get_or_create_global(now=now)
        daily_turnover, daily_order_count = self._daily_order_usage(now)
        latest_price = latest_bar.close if latest_bar is not None else None
        estimated_notional = (
            latest_bar.close * Decimal(intent.quantity)
            if latest_bar is not None
            else Decimal("0")
        )
        order, created = ExecutionOrderIntentRepository(self.session).get_or_create(
            source_type=source_type,
            source_id=source_id,
            paper_run_id=paper_run_id,
            paper_order_id=paper_order_id,
            client_order_id=client_order_id,
            symbol=intent.symbol,
            instrument_id=intent.instrument_id,
            side=intent.side.value,
            order_type=intent.order_type.value,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            estimated_price=latest_price,
            estimated_notional=estimated_notional,
            broker_mode=mode.value,
            risk_profile_name=self.profile.name,
            risk_summary_payload={"source_type": source_type, "paper_order_id": paper_order_id},
            created_at=now,
        )
        if not created and order.status != "created":
            return PreLiveSafetyDecision(
                order.id,
                "skipped",
                "skipped_duplicate_client_order_id",
                "client order id was already evaluated",
                False,
                order.approval_request_id,
            )
        policy = self.evaluate_policy(
            SafetyPolicyInput(
                intent=intent,
                latest_bar=latest_bar,
                portfolio=portfolio,
                broker_mode=mode,
                profile=self.profile,
                kill_switch_active=state.kill_switch_active,
                broker_mode_enabled=self._mode_enabled(state, mode),
                live_enabled=state.live_enabled,
                daily_turnover=daily_turnover,
                daily_order_count=daily_order_count,
                now=now,
            )
        )
        decision_repo = ExecutionOrderDecisionRepository(self.session)
        order_repo = ExecutionOrderIntentRepository(self.session)
        approval_request_id = None
        if policy.decision_type == "approved":
            ExecutionOrderStateMachine.validate(order.status, "risk_approved")
            order_repo.set_status(order, status="risk_approved", updated_at=now)
        elif policy.decision_type == "approval_required":
            approval = OperatorApprovalRequestRepository(self.session).create_pending(
                resource_type=APPROVAL_RESOURCE_TYPE,
                resource_id=order.id,
                reason_code=policy.reason_code,
                requested_by="system",
                requested_at=now,
                expires_at=now + timedelta(hours=24),
            )
            approval_request_id = approval.id
            ExecutionOrderStateMachine.validate(order.status, "approval_required")
            order_repo.set_status(
                order,
                status="approval_required",
                updated_at=now,
                approval_required=True,
                approval_request_id=approval.id,
            )
        else:
            ExecutionOrderStateMachine.validate(order.status, "blocked")
            order_repo.set_status(
                order,
                status="blocked",
                updated_at=now,
                blocked_reason_code=policy.reason_code,
                blocked_reason=policy.message,
            )
        decision_repo.record(
            order_intent_id=order.id,
            decision_type=policy.decision_type,
            reason_code=policy.reason_code,
            message=policy.message,
            policy_payload=policy.policy_payload,
            created_at=now,
        )
        return PreLiveSafetyDecision(
            order.id,
            policy.decision_type,
            policy.reason_code,
            policy.message,
            policy.broker_submission_allowed,
            approval_request_id,
        )

    def approve_order_intent(
        self,
        order_intent_id: int,
        *,
        operator: str,
        note: str,
        now: datetime,
    ) -> PreLiveSafetyDecision:
        order_repo = ExecutionOrderIntentRepository(self.session)
        order = order_repo.get(order_intent_id)
        if order is None:
            raise ValueError("execution order intent not found")
        if order.status != "approval_required" or order.approval_request_id is None:
            raise ValueError("execution order intent is not waiting for approval")
        approval_repo = OperatorApprovalRequestRepository(self.session)
        approval = approval_repo.get(order.approval_request_id)
        if approval is None:
            raise ValueError("approval request not found")
        approval_repo.decide(approval, status="approved", operator=operator, note=note, decided_at=now)
        ExecutionOrderStateMachine.validate(order.status, "operator_approved")
        order_repo.set_status(order, status="operator_approved", updated_at=now)
        ExecutionOrderDecisionRepository(self.session).record(
            order_intent_id=order.id,
            decision_type="approved",
            reason_code="approved",
            message="operator approved execution order intent",
            policy_payload={"operator": operator},
            created_at=now,
        )
        return PreLiveSafetyDecision(order.id, "approved", "approved", "operator approved execution order intent", True, approval.id)

    def reject_order_intent(
        self,
        order_intent_id: int,
        *,
        operator: str,
        note: str,
        now: datetime,
    ) -> PreLiveSafetyDecision:
        order_repo = ExecutionOrderIntentRepository(self.session)
        order = order_repo.get(order_intent_id)
        if order is None:
            raise ValueError("execution order intent not found")
        if order.status != "approval_required" or order.approval_request_id is None:
            raise ValueError("execution order intent is not waiting for approval")
        approval_repo = OperatorApprovalRequestRepository(self.session)
        approval = approval_repo.get(order.approval_request_id)
        if approval is None:
            raise ValueError("approval request not found")
        approval_repo.decide(approval, status="rejected", operator=operator, note=note, decided_at=now)
        ExecutionOrderStateMachine.validate(order.status, "blocked")
        order_repo.set_status(
            order,
            status="blocked",
            updated_at=now,
            blocked_reason_code="blocked_operator_rejected",
            blocked_reason="operator rejected execution order intent",
        )
        ExecutionOrderDecisionRepository(self.session).record(
            order_intent_id=order.id,
            decision_type="blocked",
            reason_code="blocked_operator_rejected",
            message="operator rejected execution order intent",
            policy_payload={"operator": operator},
            created_at=now,
        )
        return PreLiveSafetyDecision(order.id, "blocked", "blocked_operator_rejected", "operator rejected execution order intent", False, approval.id)

    def _mode_enabled(self, state, mode: BrokerExecutionMode) -> bool:
        if mode is BrokerExecutionMode.SIMULATED:
            return state.simulated_enabled
        if mode is BrokerExecutionMode.DRY_RUN:
            return state.dry_run_enabled
        return state.live_enabled

    def _daily_order_usage(self, now: datetime) -> tuple[Decimal, int]:
        start = datetime.combine(now.date(), datetime.min.time())
        end = datetime.combine(now.date(), datetime.max.time())
        rows = self.session.scalars(
            select(ExecutionOrderIntentORM)
            .where(ExecutionOrderIntentORM.created_at >= start)
            .where(ExecutionOrderIntentORM.created_at <= end)
            .where(ExecutionOrderIntentORM.status.in_(["risk_approved", "operator_approved", "submitted"]))
        ).all()
        turnover = sum((Decimal(row.estimated_notional) for row in rows), Decimal("0"))
        return turnover, len(rows)
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/unit/test_operations_safety.py tests/integration/test_operations_safety_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Run repository regression**

Run:

```bash
pytest tests/integration/test_operations_repositories.py -q
```

Expected: PASS.

- [ ] **Step 9: Spec review**

Check:

- Reason codes match the spec for approved, approval-required, kill switch, live blocked, broker mode disabled, stale data, invalid price, notional, exposure, turnover, daily count, drawdown, and duplicate client IDs.
- Operator approval does not submit orders.
- Live mode remains blocked.

Record:

```text
Spec review Task 2: PASS - safety policy and operator approval service implement the required pre-live gates and preserve no-live behavior.
```

- [ ] **Step 10: Quality review**

Check:

- Policy logic is deterministic and side-effect free in `evaluate_policy()`.
- Persistence happens in one session through repositories.
- State transitions are centralized.
- No unbounded message payloads are persisted.

Record:

```text
Quality review Task 2: PASS - policy logic is isolated, persistence is explicit, and state transitions are validated.
```

- [ ] **Step 11: Commit**

Run:

```bash
git add src/quant_trading/operations tests/unit/test_operations_safety.py tests/integration/test_operations_safety_service.py
git commit -m "feat: add pre-live safety service"
```

---

### Task 3: Paper Trading Integration

**Files:**
- Modify: `src/quant_trading/paper/engine.py`
- Modify: `src/quant_trading/workflows/operations.py`
- Modify: `tests/integration/test_paper_engine.py`

- [ ] **Step 1: Write failing integration tests for paper safety decisions**

Modify imports in `tests/integration/test_paper_engine.py`:

```python
from quant_trading.execution.broker import DryRunBrokerAdapter
from quant_trading.storage.models import (
    BrokerOrderEventORM,
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    ExecutionSafetyStateORM,
    OperatorApprovalRequestORM,
)
from quant_trading.storage.repositories import ExecutionSafetyStateRepository
```

Add tests:

```python
def test_paper_tick_records_pre_live_order_intent_before_simulated_broker_submission(
    legacy_sqlite_db: Path,
):
    paper, engine = make_paper_engine(legacy_sqlite_db)
    strategy = RecordingBuyStrategy()
    account_id = paper.create_account("Safety Paper", Decimal("100000"), "CNY")
    run_id = paper.start_run(
        account_id,
        "000001",
        strategy,
        strategy.name,
        StrategyStatus.APPROVED,
    )

    result = paper.run_one_tick(run_id, strategy, StrategyStatus.APPROVED)

    with session_scope(engine) as session:
        order_intent = session.scalar(select(ExecutionOrderIntentORM))
        decision = session.scalar(select(ExecutionOrderDecisionORM))
        broker_event = session.scalar(select(BrokerOrderEventORM))
    assert result.orders_created == 1
    assert result.orders_filled == 1
    assert order_intent.client_order_id == "paper-1-1"
    assert order_intent.status == "submitted"
    assert order_intent.broker_mode == "simulated"
    assert decision.reason_code == "approved"
    assert broker_event.client_order_id == order_intent.client_order_id


def test_paper_tick_kill_switch_blocks_before_broker_submission(legacy_sqlite_db: Path):
    paper, engine = make_paper_engine(legacy_sqlite_db)
    strategy = RecordingBuyStrategy()
    account_id = paper.create_account("Safety Paper", Decimal("100000"), "CNY")
    run_id = paper.start_run(
        account_id,
        "000001",
        strategy,
        strategy.name,
        StrategyStatus.APPROVED,
    )
    with session_scope(engine) as session:
        ExecutionSafetyStateRepository(session).set_kill_switch(
            active=True,
            operator="risk lead",
            reason="halt test",
            now=datetime(2026, 6, 26, 9, 0, 0),
        )

    result = paper.run_one_tick(run_id, strategy, StrategyStatus.APPROVED)

    with session_scope(engine) as session:
        order = session.scalar(select(PaperOrderORM).where(PaperOrderORM.run_id == run_id))
        order_intent = session.scalar(select(ExecutionOrderIntentORM))
        broker_events = session.scalars(select(BrokerOrderEventORM)).all()
        fills = session.scalars(select(PaperFillORM)).all()
    assert result.orders_created == 1
    assert result.orders_filled == 0
    assert result.fills_created == 0
    assert order.status == "skipped"
    assert order.risk_decision == "blocked_global_kill_switch"
    assert order_intent.status == "blocked"
    assert broker_events == []
    assert fills == []


def test_paper_tick_manual_approval_required_creates_request_and_no_broker_submission(
    legacy_sqlite_db: Path,
):
    paper, engine = make_paper_engine(legacy_sqlite_db)
    @dataclass
    class LargeBuyStrategy:
        name: str = "large_buy"

        def on_bar(self, bars, portfolio):
            latest = bars[-1]
            return [
                OrderIntent(
                    instrument_id=latest.instrument_id,
                    symbol=latest.symbol,
                    side=OrderSide.BUY,
                    quantity=6000,
                    reason="manual_approval_threshold",
                )
            ]

    strategy = LargeBuyStrategy()
    account_id = paper.create_account("Approval Paper", Decimal("1000000"), "CNY")
    run_id = paper.start_run(
        account_id,
        "000001",
        strategy,
        strategy.name,
        StrategyStatus.APPROVED,
        risk_config={"max_order_value": "1000000"},
    )

    result = paper.run_one_tick(run_id, strategy, StrategyStatus.APPROVED)

    with session_scope(engine) as session:
        order = session.scalar(select(PaperOrderORM).where(PaperOrderORM.run_id == run_id))
        order_intent = session.scalar(select(ExecutionOrderIntentORM))
        approval = session.scalar(select(OperatorApprovalRequestORM))
        broker_events = session.scalars(select(BrokerOrderEventORM)).all()
    assert result.orders_created == 1
    assert result.orders_filled == 0
    assert order.status == "skipped"
    assert order.risk_decision == "manual_approval_required_notional"
    assert order_intent.status == "approval_required"
    assert approval.status == "pending"
    assert broker_events == []


def test_paper_tick_dry_run_records_safety_and_broker_audit_without_fill(
    legacy_sqlite_db: Path,
):
    paper, engine = make_paper_engine(legacy_sqlite_db)
    paper.broker = DryRunBrokerAdapter()
    strategy = RecordingBuyStrategy()
    account_id = paper.create_account("Dry Run Paper", Decimal("100000"), "CNY")
    run_id = paper.start_run(
        account_id,
        "000001",
        strategy,
        strategy.name,
        StrategyStatus.APPROVED,
    )

    result = paper.run_one_tick(run_id, strategy, StrategyStatus.APPROVED)

    with session_scope(engine) as session:
        order_intent = session.scalar(select(ExecutionOrderIntentORM))
        broker_event = session.scalar(select(BrokerOrderEventORM))
        fills = session.scalars(select(PaperFillORM)).all()
        positions = session.scalars(select(PaperPositionORM)).all()
    assert result.orders_created == 1
    assert result.orders_filled == 0
    assert result.fills_created == 0
    assert order_intent.status == "submitted"
    assert order_intent.broker_mode == "dry_run"
    assert broker_event.status == "submitted"
    assert fills == []
    assert positions == []
```

- [ ] **Step 2: Run focused paper tests to verify they fail**

Run:

```bash
pytest tests/integration/test_paper_engine.py::test_paper_tick_records_pre_live_order_intent_before_simulated_broker_submission tests/integration/test_paper_engine.py::test_paper_tick_kill_switch_blocks_before_broker_submission tests/integration/test_paper_engine.py::test_paper_tick_manual_approval_required_creates_request_and_no_broker_submission tests/integration/test_paper_engine.py::test_paper_tick_dry_run_records_safety_and_broker_audit_without_fill -q
```

Expected: FAIL because `PaperTradingEngine` does not call the safety service.

- [ ] **Step 3: Modify `PaperTradingEngine` constructor**

Modify `src/quant_trading/paper/engine.py` imports:

```python
from datetime import date, datetime

from quant_trading.execution.broker import BrokerExecutionMode
from quant_trading.operations.safety import PreLiveSafetyService
```

Modify constructor:

```python
    def __init__(
        self,
        engine: Engine,
        initial_cash: Decimal,
        risk_engine: RiskEngine,
        commission_rate: Decimal = Decimal("0.0003"),
        slippage_rate: Decimal = Decimal("0.001"),
        broker_adapter: BrokerAdapter | None = None,
        enable_pre_live_safety: bool = True,
    ):
        self.engine = engine
        self.initial_cash = initial_cash
        self.risk_engine = risk_engine
        self.broker = broker_adapter or SimulatedBrokerAdapter(
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
        )
        self.enable_pre_live_safety = enable_pre_live_safety
```

- [ ] **Step 4: Evaluate safety before broker submission**

In `run_one_tick()`, after existing risk approval and before `broker_order_request_from_intent()`, add:

```python
                client_order_id = f"paper-{run.id}-{order.id}"
                if self.enable_pre_live_safety:
                    safety_now = self._safety_now(latest.timestamp)
                    safety_decision = PreLiveSafetyService(session).evaluate_order_intent(
                        intent=intent,
                        latest_bar=latest,
                        portfolio=portfolio,
                        broker_mode=BrokerExecutionMode(self.broker.mode),
                        source_type="paper_run",
                        source_id=run.id,
                        paper_run_id=run.id,
                        paper_order_id=order.id,
                        client_order_id=client_order_id,
                        now=safety_now,
                    )
                    if not safety_decision.broker_submission_allowed:
                        repository.mark_order_skipped(order, safety_decision.reason_code)
                        continue
```

Change broker request construction to reuse `client_order_id`:

```python
                request = broker_order_request_from_intent(
                    intent,
                    latest,
                    client_order_id=client_order_id,
                )
```

After the existing broker order event repository call records the broker adapter result,
mark the safety order intent submitted:

```python
                if self.enable_pre_live_safety:
                    PreLiveSafetyService(session).mark_order_intent_submitted(
                        safety_decision.order_intent_id,
                        submitted_at=safety_now,
                    )
```

Add `mark_order_intent_submitted()` to `PreLiveSafetyService`:

```python
    def mark_order_intent_submitted(
        self,
        order_intent_id: int,
        *,
        submitted_at: datetime,
    ) -> None:
        order_repo = ExecutionOrderIntentRepository(self.session)
        order = order_repo.get(order_intent_id)
        if order is None:
            raise ValueError("execution order intent not found")
        ExecutionOrderStateMachine.validate(order.status, "submitted")
        order_repo.set_status(
            order,
            status="submitted",
            updated_at=submitted_at,
            submitted_at=submitted_at,
        )
```

Add a helper method to `PaperTradingEngine` so historical fixture data is not
misclassified as stale during local paper tests:

```python
    def _safety_now(self, timestamp: date | datetime | str) -> datetime:
        if isinstance(timestamp, datetime):
            return timestamp
        if isinstance(timestamp, date):
            return datetime.combine(timestamp, datetime.min.time())
        return datetime.fromisoformat(str(timestamp))
```

- [ ] **Step 5: Preserve workflow construction**

Modify `_make_paper_engine()` in `src/quant_trading/workflows/operations.py` to pass `enable_pre_live_safety=True` explicitly:

```python
    return PaperTradingEngine(
        engine=engine,
        initial_cash=initial_cash,
        risk_engine=RiskEngine(
            [
                StrategyStatusRule(),
                NoTradeWithoutDataRule(),
                PriceSanityRule(),
                MaxOrderValueRule(max_order_value=max_order_value),
            ]
        ),
        commission_rate=DEFAULT_COMMISSION_RATE,
        slippage_rate=DEFAULT_SLIPPAGE_RATE,
        enable_pre_live_safety=True,
    )
```

- [ ] **Step 6: Run focused paper tests**

Run:

```bash
pytest tests/integration/test_paper_engine.py -q
```

Expected: PASS.

- [ ] **Step 7: Run paper workflow regressions**

Run:

```bash
pytest tests/integration/test_paper_lifecycle.py tests/integration/test_paper_jobs.py tests/integration/test_workflows_service.py tests/integration/test_operations_workflow_e2e.py -q
```

Expected: PASS.

- [ ] **Step 8: Spec review**

Check:

- Safety service runs after existing `RiskEngine` approval and before broker adapter submission.
- Blocked and approval-required decisions create no broker events, fills, or positions.
- Dry-run creates broker audit rows but no fills or positions.
- Existing simulated paper path still fills when checks pass.

Record:

```text
Spec review Task 3: PASS - paper integration inserts the pre-live safety gate at the required boundary without adding live execution.
```

- [ ] **Step 9: Quality review**

Check:

- The paper tick transaction records safety decisions, broker audit, fills, and portfolio state consistently.
- Safety service failures prevent broker submission.
- Existing idempotent no-op behavior remains based on `run.last_processed_at`.

Record:

```text
Quality review Task 3: PASS - transaction order is clear, broker submission is guarded, and legacy simulated behavior remains covered by tests.
```

- [ ] **Step 10: Commit**

Run:

```bash
git add src/quant_trading/paper/engine.py src/quant_trading/workflows/operations.py src/quant_trading/operations/safety.py tests/integration/test_paper_engine.py
git commit -m "feat: gate paper orders with pre-live safety"
```

---

### Task 4: Operations API And Readiness Service

**Files:**
- Create: `src/quant_trading/operations/readiness.py`
- Create: `src/quant_trading/api/routes/operations.py`
- Modify: `src/quant_trading/api/main.py`
- Create: `tests/integration/test_operations_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/integration/test_operations_api.py`.

```python
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import (
    ExecutionSafetyStateRepository,
    OperatorApprovalRequestRepository,
    SafetyIncidentRepository,
)


def _client(settings=None):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine, settings=settings)), engine


def test_ops_readiness_reports_default_non_live_posture():
    client, _ = _client()

    response = client.get("/ops/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["broker_mode"] == "simulated"
    assert payload["global_kill_switch_active"] is False
    assert payload["live_execution_available"] is False
    assert payload["safe_for_simulated_paper"] is True
    assert payload["safe_for_dry_run"] is True
    assert payload["safe_for_live"] is False
    assert "live_execution_unavailable" in payload["reasons"]


def test_ops_kill_switch_enable_disable_writes_events_and_changes_readiness():
    client, _ = _client()

    enabled = client.post(
        "/ops/kill-switch/enable",
        json={"operator": "risk lead", "reason": "manual pause"},
    )
    disabled = client.post(
        "/ops/kill-switch/disable",
        json={"operator": "risk lead", "reason": "resume simulated testing"},
    )
    events = client.get("/ops/kill-switch-events")

    assert enabled.status_code == 200
    assert enabled.json()["kill_switch_active"] is True
    assert disabled.status_code == 200
    assert disabled.json()["kill_switch_active"] is False
    assert events.status_code == 200
    assert len(events.json()) == 2
    assert events.json()[0]["operator"] == "risk lead"


def test_ops_incident_acknowledge_and_resolve():
    client, engine = _client()
    now = datetime(2026, 6, 26, 9, 0, 0)
    with session_scope(engine) as session:
        incident = SafetyIncidentRepository(session).create(
            severity="warning",
            category="stale_data",
            resource_type=None,
            resource_id=None,
            reason_code="blocked_stale_market_data",
            message="stale data",
            payload={},
            created_at=now,
        )
        incident_id = incident.id

    acknowledged = client.post(
        f"/ops/incidents/{incident_id}/acknowledge",
        json={"operator": "ops", "note": "checking"},
    )
    resolved = client.post(
        f"/ops/incidents/{incident_id}/resolve",
        json={"operator": "ops", "note": "fixed"},
    )

    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_ops_commands_are_auth_protected_when_auth_enabled():
    settings = AppSettings(
        require_auth=True,
        api_token="secret-token",
        public_routes=["/health"],
    )
    client, _ = _client(settings)

    denied = client.post(
        "/ops/kill-switch/enable",
        json={"operator": "risk", "reason": "pause"},
    )
    allowed = client.post(
        "/ops/kill-switch/enable",
        json={"operator": "risk", "reason": "pause"},
        headers={"Authorization": "Bearer secret-token"},
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
pytest tests/integration/test_operations_api.py -q
```

Expected: FAIL because operations routes do not exist.

- [ ] **Step 3: Implement readiness builder**

Create `src/quant_trading/operations/readiness.py`.

```python
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_trading.config import AppSettings
from quant_trading.storage.models import (
    DataQualityReportORM,
    DataSyncRunORM,
    JobRunORM,
    OperatorApprovalRequestORM,
    ResearchValidationReportORM,
    SafetyIncidentORM,
)
from quant_trading.storage.repositories import ExecutionSafetyStateRepository


def build_operations_readiness(
    session: Session,
    *,
    settings: AppSettings,
    now: datetime,
) -> dict[str, Any]:
    safety_state = ExecutionSafetyStateRepository(session).get_or_create_global(now=now)
    stale_cutoff = now - timedelta(hours=2)
    failed_cutoff = now - timedelta(hours=24)
    open_critical = session.scalar(
        select(func.count())
        .select_from(SafetyIncidentORM)
        .where(SafetyIncidentORM.status != "resolved")
        .where(SafetyIncidentORM.severity == "critical")
    ) or 0
    open_warning = session.scalar(
        select(func.count())
        .select_from(SafetyIncidentORM)
        .where(SafetyIncidentORM.status != "resolved")
        .where(SafetyIncidentORM.severity == "warning")
    ) or 0
    pending_approvals = session.scalar(
        select(func.count())
        .select_from(OperatorApprovalRequestORM)
        .where(OperatorApprovalRequestORM.status == "pending")
    ) or 0
    stuck_jobs = session.scalar(
        select(func.count())
        .select_from(JobRunORM)
        .where(JobRunORM.status.in_(["queued", "running", "cancel_requested"]))
        .where(JobRunORM.updated_at < stale_cutoff)
    ) or 0
    failed_jobs_24h = session.scalar(
        select(func.count())
        .select_from(JobRunORM)
        .where(JobRunORM.status == "failed")
        .where(JobRunORM.updated_at >= failed_cutoff)
    ) or 0
    stale_data_reports = session.scalar(
        select(func.count())
        .select_from(DataQualityReportORM)
        .where(DataQualityReportORM.stale_data.is_(True))
    ) or 0
    latest_data_sync = session.scalar(
        select(DataSyncRunORM).order_by(DataSyncRunORM.id.desc()).limit(1)
    )
    latest_validation = session.scalar(
        select(ResearchValidationReportORM)
        .order_by(ResearchValidationReportORM.id.desc())
        .limit(1)
    )
    reasons = []
    if safety_state.kill_switch_active:
        reasons.append("global_kill_switch_active")
    if open_critical:
        reasons.append("open_critical_incidents")
    if pending_approvals:
        reasons.append("pending_operator_approvals")
    reasons.append("live_execution_unavailable")

    safe_for_simulated = (
        not safety_state.kill_switch_active
        and safety_state.simulated_enabled
        and open_critical == 0
    )
    safe_for_dry_run = (
        not safety_state.kill_switch_active
        and safety_state.dry_run_enabled
        and open_critical == 0
    )
    return {
        "environment": settings.app_env,
        "trading_enabled": settings.trading_enabled,
        "broker_mode": settings.broker_mode,
        "global_kill_switch_active": safety_state.kill_switch_active,
        "live_execution_available": False,
        "open_critical_incidents": open_critical,
        "open_warning_incidents": open_warning,
        "pending_approval_requests": pending_approvals,
        "stuck_jobs": stuck_jobs,
        "failed_jobs_24h": failed_jobs_24h,
        "stale_data_reports": stale_data_reports,
        "latest_data_sync_status": (
            {"id": latest_data_sync.id, "status": latest_data_sync.status}
            if latest_data_sync is not None
            else None
        ),
        "latest_research_validation_status": (
            {
                "id": latest_validation.id,
                "status": latest_validation.validation_status,
                "readiness_floor": latest_validation.readiness_floor,
            }
            if latest_validation is not None
            else None
        ),
        "safe_for_simulated_paper": safe_for_simulated,
        "safe_for_dry_run": safe_for_dry_run,
        "safe_for_live": False,
        "reasons": reasons,
    }
```

- [ ] **Step 4: Implement operations routes**

Create `src/quant_trading/api/routes/operations.py`.

```python
from datetime import datetime
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from quant_trading.operations.readiness import build_operations_readiness
from quant_trading.operations.safety import PreLiveSafetyService
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import (
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    KillSwitchEventORM,
    OperatorApprovalRequestORM,
    SafetyIncidentORM,
)
from quant_trading.storage.repositories import (
    ExecutionSafetyStateRepository,
    KillSwitchEventRepository,
    OperatorApprovalRequestRepository,
    SafetyIncidentRepository,
)

router = APIRouter(prefix="/ops", tags=["operations"])


class OperatorReasonPayload(BaseModel):
    operator: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1024)

    @field_validator("operator", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value is required")
        return value


class OperatorNotePayload(BaseModel):
    operator: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1, max_length=2048)

    @field_validator("operator", "note")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value is required")
        return value


@router.get("/readiness")
def get_readiness(request: Request) -> dict:
    with session_scope(request.app.state.engine) as session:
        return build_operations_readiness(
            session,
            settings=request.app.state.settings,
            now=datetime.utcnow(),
        )


@router.get("/safety-state")
def get_safety_state(request: Request) -> dict:
    with session_scope(request.app.state.engine) as session:
        repo = ExecutionSafetyStateRepository(session)
        state = repo.get_or_create_global(now=datetime.utcnow())
        return repo.payload(state)


@router.post("/kill-switch/enable")
def enable_kill_switch(payload: OperatorReasonPayload, request: Request) -> dict:
    return _set_kill_switch(request, active=True, operator=payload.operator, reason=payload.reason)


@router.post("/kill-switch/disable")
def disable_kill_switch(payload: OperatorReasonPayload, request: Request) -> dict:
    return _set_kill_switch(request, active=False, operator=payload.operator, reason=payload.reason)


def _set_kill_switch(request: Request, *, active: bool, operator: str, reason: str) -> dict:
    now = datetime.utcnow()
    with session_scope(request.app.state.engine) as session:
        state_repo = ExecutionSafetyStateRepository(session)
        state = state_repo.get_or_create_global(now=now)
        previous = state_repo.payload(state)
        updated = state_repo.set_kill_switch(active=active, operator=operator, reason=reason, now=now)
        KillSwitchEventRepository(session).record(
            scope="global",
            previous_state_payload=previous,
            new_state_payload=state_repo.payload(updated),
            operator=operator,
            reason=reason,
            created_at=now,
        )
        return state_repo.payload(updated)


@router.get("/order-intents")
def list_order_intents(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = session.query(ExecutionOrderIntentORM).order_by(ExecutionOrderIntentORM.id.desc()).limit(50).all()
        return [_order_intent_payload(row) for row in rows]


@router.get("/order-intents/{order_intent_id}")
def get_order_intent(order_intent_id: int, request: Request) -> dict:
    with session_scope(request.app.state.engine) as session:
        row = session.get(ExecutionOrderIntentORM, order_intent_id)
        if row is None:
            raise HTTPException(status_code=404, detail="execution order intent not found")
        decisions = session.query(ExecutionOrderDecisionORM).filter_by(order_intent_id=order_intent_id).order_by(ExecutionOrderDecisionORM.id).all()
        payload = _order_intent_payload(row)
        payload["decisions"] = [_decision_payload(item) for item in decisions]
        return payload


@router.get("/approval-requests")
def list_approval_requests(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = OperatorApprovalRequestRepository(session).list_recent(limit=50)
        return [_approval_payload(row) for row in rows]


@router.post("/order-intents/{order_intent_id}/approve")
def approve_order_intent(order_intent_id: int, payload: OperatorNotePayload, request: Request) -> dict:
    with session_scope(request.app.state.engine) as session:
        try:
            decision = PreLiveSafetyService(session).approve_order_intent(
                order_intent_id,
                operator=payload.operator,
                note=payload.note,
                now=datetime.utcnow(),
            )
        except ValueError as exc:
            _raise_ops_error(exc)
        return decision.__dict__


@router.post("/order-intents/{order_intent_id}/reject")
def reject_order_intent(order_intent_id: int, payload: OperatorNotePayload, request: Request) -> dict:
    with session_scope(request.app.state.engine) as session:
        try:
            decision = PreLiveSafetyService(session).reject_order_intent(
                order_intent_id,
                operator=payload.operator,
                note=payload.note,
                now=datetime.utcnow(),
            )
        except ValueError as exc:
            _raise_ops_error(exc)
        return decision.__dict__


@router.get("/incidents")
def list_incidents(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = SafetyIncidentRepository(session).list_recent(limit=50)
        return [_incident_payload(row) for row in rows]


@router.post("/incidents/{incident_id}/acknowledge")
def acknowledge_incident(incident_id: int, payload: OperatorNotePayload, request: Request) -> dict:
    with session_scope(request.app.state.engine) as session:
        repo = SafetyIncidentRepository(session)
        row = repo.get(incident_id)
        if row is None:
            raise HTTPException(status_code=404, detail="safety incident not found")
        try:
            repo.acknowledge(row, operator=payload.operator, acknowledged_at=datetime.utcnow())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _incident_payload(row)


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: int, payload: OperatorNotePayload, request: Request) -> dict:
    with session_scope(request.app.state.engine) as session:
        repo = SafetyIncidentRepository(session)
        row = repo.get(incident_id)
        if row is None:
            raise HTTPException(status_code=404, detail="safety incident not found")
        repo.resolve(row, operator=payload.operator, resolved_at=datetime.utcnow())
        return _incident_payload(row)


@router.get("/kill-switch-events")
def list_kill_switch_events(request: Request) -> list[dict]:
    with session_scope(request.app.state.engine) as session:
        rows = KillSwitchEventRepository(session).list_recent(limit=50)
        return [_kill_switch_event_payload(row) for row in rows]


def _raise_ops_error(exc: ValueError) -> None:
    message = str(exc)
    if "not found" in message:
        raise HTTPException(status_code=404, detail=message) from exc
    raise HTTPException(status_code=409, detail=message) from exc


def _order_intent_payload(row: ExecutionOrderIntentORM) -> dict:
    return {
        "id": row.id,
        "client_order_id": row.client_order_id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "paper_run_id": row.paper_run_id,
        "paper_order_id": row.paper_order_id,
        "symbol": row.symbol,
        "instrument_id": row.instrument_id,
        "side": row.side,
        "order_type": row.order_type,
        "quantity": row.quantity,
        "estimated_notional": float(row.estimated_notional),
        "broker_mode": row.broker_mode,
        "status": row.status,
        "risk_profile_name": row.risk_profile_name,
        "approval_required": row.approval_required,
        "approval_request_id": row.approval_request_id,
        "blocked_reason_code": row.blocked_reason_code,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _decision_payload(row: ExecutionOrderDecisionORM) -> dict:
    return {
        "id": row.id,
        "order_intent_id": row.order_intent_id,
        "decision_type": row.decision_type,
        "reason_code": row.reason_code,
        "message": row.message,
        "policy_payload": json.loads(row.policy_payload or "{}"),
        "created_at": row.created_at.isoformat(),
    }


def _approval_payload(row: OperatorApprovalRequestORM) -> dict:
    return {
        "id": row.id,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "status": row.status,
        "reason_code": row.reason_code,
        "requested_by": row.requested_by,
        "requested_at": row.requested_at.isoformat(),
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "operator_note": row.operator_note,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def _incident_payload(row: SafetyIncidentORM) -> dict:
    return {
        "id": row.id,
        "severity": row.severity,
        "category": row.category,
        "status": row.status,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "reason_code": row.reason_code,
        "message": row.message,
        "payload": json.loads(row.payload or "{}"),
        "created_at": row.created_at.isoformat(),
    }


def _kill_switch_event_payload(row: KillSwitchEventORM) -> dict:
    return {
        "id": row.id,
        "scope": row.scope,
        "previous_state_payload": json.loads(row.previous_state_payload or "{}"),
        "new_state_payload": json.loads(row.new_state_payload or "{}"),
        "operator": row.operator,
        "reason": row.reason,
        "created_at": row.created_at.isoformat(),
    }
```

- [ ] **Step 5: Register router**

Modify `src/quant_trading/api/main.py`.

Add import in the routes tuple:

```python
    operations,
```

Include before dashboard:

```python
    app.include_router(operations.router)
```

- [ ] **Step 6: Run focused API tests**

Run:

```bash
pytest tests/integration/test_operations_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Run API regression tests**

Run:

```bash
pytest tests/integration/test_api.py tests/integration/test_runtime_auth.py tests/integration/test_workflows_api.py tests/integration/test_jobs_api.py -q
```

Expected: PASS.

- [ ] **Step 8: Spec review**

Check:

- All required `/ops/*` endpoints exist.
- Kill-switch commands require operator and reason.
- Approval endpoints update safety state only and do not submit broker orders.
- Readiness reports `safe_for_live=false` and `live_execution_available=false`.

Record:

```text
Spec review Task 4: PASS - operations APIs and readiness output match the safety ops spec and keep live execution unavailable.
```

- [ ] **Step 9: Quality review**

Check:

- API error mapping uses 404 for missing rows and 409 for invalid state transitions.
- Auth middleware protects command endpoints when auth is enabled.
- Response payloads decode stored JSON safely and avoid raw exception traces.

Record:

```text
Quality review Task 4: PASS - API payloads are bounded, errors are explicit, and command routes remain protected by existing auth middleware.
```

- [ ] **Step 10: Commit**

Run:

```bash
git add src/quant_trading/operations/readiness.py src/quant_trading/api/routes/operations.py src/quant_trading/api/main.py tests/integration/test_operations_api.py
git commit -m "feat: expose pre-live operations api"
```

---

### Task 5: Dashboard And README

**Files:**
- Modify: `src/quant_trading/api/routes/dashboard.py`
- Modify: `tests/integration/test_dashboard.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing dashboard test**

Modify `tests/integration/test_dashboard.py`.

Add:

```python
def test_dashboard_displays_operations_safety_section():
    from datetime import datetime

    from quant_trading.storage.repositories import (
        ExecutionSafetyStateRepository,
        KillSwitchEventRepository,
        SafetyIncidentRepository,
    )

    client, engine = make_client()
    now = datetime(2026, 6, 26, 9, 0, 0)
    with session_scope(engine) as session:
        state_repo = ExecutionSafetyStateRepository(session)
        state = state_repo.get_or_create_global(now=now)
        previous = state_repo.payload(state)
        updated = state_repo.set_kill_switch(
            active=True,
            operator="risk lead",
            reason="dashboard test pause",
            now=now,
        )
        KillSwitchEventRepository(session).record(
            scope="global",
            previous_state_payload=previous,
            new_state_payload=state_repo.payload(updated),
            operator="risk lead",
            reason="dashboard test pause",
            created_at=now,
        )
        SafetyIncidentRepository(session).create(
            severity="warning",
            category="stale_data",
            resource_type=None,
            resource_id=None,
            reason_code="blocked_stale_market_data",
            message="stale market data",
            payload={},
            created_at=now,
        )

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Operations Safety" in html
    assert "Kill Switch" in html
    assert "active" in html
    assert "Safe For Live" in html
    assert "false" in html
    assert "dashboard test pause" in html
    assert "stale market data" in html
```

- [ ] **Step 2: Run dashboard test to verify it fails**

Run:

```bash
pytest tests/integration/test_dashboard.py::test_dashboard_displays_operations_safety_section -q
```

Expected: FAIL because dashboard does not render operations safety.

- [ ] **Step 3: Add safety state collection**

Modify imports in `src/quant_trading/api/routes/dashboard.py`:

```python
from datetime import datetime

from quant_trading.operations.readiness import build_operations_readiness
from quant_trading.storage.models import (
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    KillSwitchEventORM,
    OperatorApprovalRequestORM,
    SafetyIncidentORM,
)
```

In `_collect_state()`, add:

```python
            "ops_readiness": build_operations_readiness(
                session,
                settings=settings,
                now=datetime.utcnow(),
            ),
            "ops_order_intents": _latest(session, ExecutionOrderIntentORM),
            "ops_decisions": _latest(session, ExecutionOrderDecisionORM),
            "ops_approvals": _latest(session, OperatorApprovalRequestORM),
            "ops_incidents": _latest(session, SafetyIncidentORM),
            "ops_kill_switch_events": _latest(session, KillSwitchEventORM),
```

- [ ] **Step 4: Render `Operations Safety` section**

Add this call near the top of `_render_dashboard()` after the meta section:

```python
  {_operations_safety_section(state)}
```

Add helper:

```python
def _operations_safety_section(state: dict[str, Any]) -> str:
    readiness = state["ops_readiness"]
    return f"""
  <h2>Operations Safety</h2>
  <section class="meta" aria-label="Operations safety">
    <div class="metric"><span>Kill Switch</span>{_e("active" if readiness["global_kill_switch_active"] else "inactive")}</div>
    <div class="metric"><span>Safe For Simulated</span>{_e(str(readiness["safe_for_simulated_paper"]).lower())}</div>
    <div class="metric"><span>Safe For Dry Run</span>{_e(str(readiness["safe_for_dry_run"]).lower())}</div>
    <div class="metric"><span>Safe For Live</span>{_e(str(readiness["safe_for_live"]).lower())}</div>
    <div class="metric"><span>Pending Approvals</span>{_e(readiness["pending_approval_requests"])}</div>
    <div class="metric"><span>Open Incidents</span>{_e(readiness["open_critical_incidents"] + readiness["open_warning_incidents"])}</div>
  </section>
  {_table("Recent Safety Decisions", ["ID", "Order", "Decision", "Reason", "Created"], state["ops_decisions"], lambda r: [f"#{r.id}", f"#{r.order_intent_id}", r.decision_type, r.reason_code, r.created_at])}
  {_table("Recent Order Intents", ["ID", "Client Order", "Symbol", "Mode", "Status", "Reason"], state["ops_order_intents"], lambda r: [f"#{r.id}", r.client_order_id, r.symbol, r.broker_mode, r.status, r.blocked_reason_code or ""])}
  {_table("Recent Approval Requests", ["ID", "Resource", "Status", "Reason", "Requested"], state["ops_approvals"], lambda r: [f"#{r.id}", f"{r.resource_type} #{r.resource_id}", r.status, r.reason_code, r.requested_at])}
  {_table("Recent Safety Incidents", ["ID", "Severity", "Category", "Status", "Reason", "Message"], state["ops_incidents"], lambda r: [f"#{r.id}", r.severity, r.category, r.status, r.reason_code, r.message])}
  {_table("Recent Kill Switch Events", ["ID", "Operator", "Reason", "Created"], state["ops_kill_switch_events"], lambda r: [f"#{r.id}", r.operator, r.reason, r.created_at])}
"""
```

- [ ] **Step 5: Run dashboard tests**

Run:

```bash
pytest tests/integration/test_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 6: Update README**

Modify `README.md`.

Add endpoints to the API endpoints list:

```text
http://localhost:8000/ops/readiness
http://localhost:8000/ops/safety-state
http://localhost:8000/ops/order-intents
http://localhost:8000/ops/order-intents/{order_intent_id}
http://localhost:8000/ops/order-intents/{order_intent_id}/approve
http://localhost:8000/ops/order-intents/{order_intent_id}/reject
http://localhost:8000/ops/approval-requests
http://localhost:8000/ops/incidents
http://localhost:8000/ops/incidents/{incident_id}/acknowledge
http://localhost:8000/ops/incidents/{incident_id}/resolve
http://localhost:8000/ops/kill-switch-events
http://localhost:8000/ops/kill-switch/enable
http://localhost:8000/ops/kill-switch/disable
```

Add a section after broker adapter safety:

```markdown
### Pre-Live Safety And Operations

The pre-live safety layer records every execution-bound paper order intent before broker
adapter submission. It evaluates the global kill switch, broker mode availability, stale
data, invalid prices, notional limits, gross exposure, daily turnover, daily order count,
drawdown stops, and manual approval thresholds.

Default local behavior remains safe and usable:

- `QUANT_TRADING_ENABLED=false`
- `QUANT_BROKER_MODE=simulated`
- global kill switch inactive
- simulated and dry-run modes enabled
- live execution unavailable

Read readiness:

```bash
curl http://127.0.0.1:8000/ops/readiness
```

Enable the kill switch:

```bash
curl -X POST http://127.0.0.1:8000/ops/kill-switch/enable \
  -H "Content-Type: application/json" \
  -d '{"operator":"risk lead","reason":"pause while checking data quality"}'
```

Disable the kill switch for simulated or dry-run testing:

```bash
curl -X POST http://127.0.0.1:8000/ops/kill-switch/disable \
  -H "Content-Type: application/json" \
  -d '{"operator":"risk lead","reason":"resume simulated paper testing"}'
```

Operator approval of an execution order intent is only an audit/state transition. It
does not submit an order by itself. This project still does not include real broker
integration, live order placement, broker credentials, live order polling, or generated
strategy execution.
```

- [ ] **Step 7: Run docs/dash verification**

Run:

```bash
pytest tests/integration/test_dashboard.py tests/integration/test_operations_api.py -q
git diff --check
```

Expected: PASS and no diff-check output.

- [ ] **Step 8: Spec review**

Check:

- Dashboard shows kill switch, broker/trading state, readiness booleans, pending approvals, incidents, decisions, and kill-switch events.
- README states no live trading, no broker credentials, and no automatic order submission.

Record:

```text
Spec review Task 5: PASS - dashboard and README expose the operations safety posture without implying live readiness.
```

- [ ] **Step 9: Quality review**

Check:

- Dashboard text fits the existing dense operations workbench style.
- README examples use local endpoints and do not include secrets.
- The dashboard does not add nested cards or unrelated UI changes.

Record:

```text
Quality review Task 5: PASS - dashboard additions follow existing server-rendered patterns and README examples preserve safety boundaries.
```

- [ ] **Step 10: Commit**

Run:

```bash
git add src/quant_trading/api/routes/dashboard.py tests/integration/test_dashboard.py README.md
git commit -m "docs: document pre-live safety operations"
```

---

### Task 6: Full Verification And Final Review

**Files:**
- Review-only verification by default.
- If verification exposes a defect, edit only the file named by the failing test or review finding, then rerun this task from Step 1.

- [ ] **Step 1: Run focused operations suite**

Run:

```bash
pytest tests/unit/test_operations_safety.py tests/integration/test_operations_repositories.py tests/integration/test_operations_safety_service.py tests/integration/test_operations_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run paper/broker/regression suite**

Run:

```bash
pytest tests/unit/test_broker_adapter.py tests/unit/test_risk_engine.py tests/integration/test_broker_order_events_repository.py tests/integration/test_paper_engine.py tests/integration/test_paper_lifecycle.py tests/integration/test_paper_jobs.py -q
```

Expected: PASS.

- [ ] **Step 3: Run migration/API/dashboard suite**

Run:

```bash
pytest tests/integration/test_migrations.py tests/integration/test_api.py tests/integration/test_runtime_auth.py tests/integration/test_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full test suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 5: Run compile check**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m compileall -q src
```

Expected: PASS with no output.

- [ ] **Step 6: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: PASS with no output.

- [ ] **Step 7: Final spec compliance review**

Use this checklist:

```text
- Durable order-intent state machine exists.
- Risk profile exists with the required default limits.
- Operator approval requests exist and are separate from candidate approval.
- Kill-switch state and events exist.
- Readiness summarizes jobs, incidents, stale data, pending approvals, and live false.
- Paper engine gates broker submission with safety service.
- Blocked and approval-required paths call no broker adapter.
- Dry-run creates no fills or positions.
- Agent output cannot directly create execution orders.
- No real broker SDK, live order placement, credentials, polling, or webhooks were added.
- README and dashboard state the safety posture accurately.
```

Record:

```text
Final spec review: PASS - implementation satisfies the pre-live safety ops spec and preserves all non-goals.
```

- [ ] **Step 8: Final quality review**

Use this checklist:

```text
- State transitions are centralized and tested.
- Repository methods are transaction-scoped.
- API errors are 404/409/422 where expected.
- JSON payloads and messages are capped.
- Tests cover blocked, approval-required, approved simulated, and dry-run behavior.
- Migration upgrades and downgrades are reversible.
- Full suite, compileall, and diff check pass.
```

Record:

```text
Final quality review: PASS - safety boundaries, persistence, API behavior, and tests are production-oriented for a pre-live paper environment.
```

- [ ] **Step 9: Commit any final fixes**

If verification required fixes, stage only files that belong to this plan and commit them:

```bash
git add src/quant_trading tests README.md migrations/versions/20260626_0010_add_pre_live_safety_ops.py
git commit -m "fix: harden pre-live safety operations"
```

If no fixes were needed, do not create an empty commit.

- [ ] **Step 10: Stop before push or merge**

Do not push or merge unless the user explicitly asks. Report:

```text
Pre-live safety ops implementation complete locally. Full verification passed: pytest -q, compileall, and git diff --check.
```
