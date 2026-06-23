# Quant Trading Broker Order Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every paper-engine broker adapter submission as an append-only audit row.

**Architecture:** Add `broker_order_events` to the SQLAlchemy/Alembic runtime schema, implement a focused repository that serializes normalized `BrokerOrderRequest` and `BrokerOrderResult` objects, and call it from `PaperTradingEngine` immediately after `broker.submit_order()`. Keep the audit internal; no API/dashboard expansion in this stage.

**Tech Stack:** SQLAlchemy 2.x, Alembic, pytest, existing paper engine, existing broker adapter dataclasses.

---

## Baseline

```bash
cd /private/tmp/quant-stage4-runtime
git status --short --branch
```

Expected: branch `codex/quant-stage4-runtime-tmp`; worktree clean after design commit.

Primary design: `docs/superpowers/specs/2026-06-23-quant-trading-broker-order-audit-design.md`

## File Structure

Create:

- `migrations/versions/20260623_0006_add_broker_order_events.py` - Alembic migration for broker audit table.
- `tests/integration/test_broker_order_events_repository.py` - repository coverage.

Modify:

- `src/quant_trading/storage/models.py` - add `BrokerOrderEventORM`.
- `src/quant_trading/storage/repositories.py` - add `BrokerOrderEventRepository`.
- `src/quant_trading/paper/engine.py` - record broker order events after adapter submission.
- `tests/integration/test_migrations.py` - assert table exists.
- `tests/integration/test_paper_engine.py` - assert simulated and dry-run ticks create audit rows.
- `README.md` - document broker order audit.

## Task 1: Schema And Repository

**Files:**

- Modify: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_broker_order_events_repository.py`
- Modify: `src/quant_trading/storage/models.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `migrations/versions/20260623_0006_add_broker_order_events.py`

- [ ] **Step 1: Write failing migration assertion**

Modify `tests/integration/test_migrations.py` by adding:

```python
    assert "broker_order_events" in tables
```

near the existing table assertions.

- [ ] **Step 2: Write failing repository test**

Create `tests/integration/test_broker_order_events_repository.py`:

```python
from datetime import date
from decimal import Decimal
import json

from quant_trading.core.enums import Market, OrderSide, OrderStatus, OrderType
from quant_trading.core.models import Bar, OrderIntent
from quant_trading.execution.broker import (
    BrokerExecutionMode,
    BrokerOrderResult,
    broker_order_request_from_intent,
)
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import BrokerOrderEventRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_broker_order_event_repository_records_request_and_result_payloads():
    engine = make_engine_with_schema()
    bar = Bar(
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
    intent = OrderIntent(
        instrument_id=1,
        symbol="000001",
        side=OrderSide.BUY,
        quantity=100,
        reason="audit_test",
        order_type=OrderType.MARKET,
    )
    request = broker_order_request_from_intent(intent, bar, "client-1")
    result = BrokerOrderResult(
        broker_order_id="dry-run-client-1",
        status=OrderStatus.SUBMITTED,
        mode=BrokerExecutionMode.DRY_RUN,
        accepted=True,
        message="dry-run accepted",
    )

    with session_scope(engine) as session:
        row = BrokerOrderEventRepository(session).record_from_broker_result(
            run_id=11,
            order_id=22,
            request=request,
            result=result,
            created_at=date(2026, 5, 8),
        )
        event_id = row.id

    with session_scope(engine) as session:
        repo = BrokerOrderEventRepository(session)
        rows = repo.list_for_order(22)
        row = repo.get(event_id)

        assert len(rows) == 1
        assert row.broker_mode == "dry_run"
        assert row.client_order_id == "client-1"
        assert row.broker_order_id == "dry-run-client-1"
        assert row.status == "submitted"
        assert row.accepted is True
        assert json.loads(row.request_payload)["symbol"] == "000001"
        assert json.loads(row.result_payload)["has_fill"] is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/integration/test_migrations.py tests/integration/test_broker_order_events_repository.py -q
```

Expected: FAIL because `broker_order_events`, `BrokerOrderEventORM`, and `BrokerOrderEventRepository` do not exist.

- [ ] **Step 4: Add ORM model**

Modify `src/quant_trading/storage/models.py` after `RiskDecisionORM`:

```python
class BrokerOrderEventORM(Base):
    __tablename__ = "broker_order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_runs.id"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_orders.id"), nullable=True, index=True
    )
    broker_mode: Mapped[str] = mapped_column(String(32), index=True)
    client_order_id: Mapped[str] = mapped_column(String(128), index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    request_payload: Mapped[str] = mapped_column(Text, default="{}")
    result_payload: Mapped[str] = mapped_column(Text, default="{}")
    message: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
```

- [ ] **Step 5: Add repository**

Modify `src/quant_trading/storage/repositories.py` imports:

```python
from quant_trading.execution.broker import BrokerOrderRequest, BrokerOrderResult
```

Import `BrokerOrderEventORM` from storage models.

Add helper functions near `_json_dumps` if needed:

```python
def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _json_dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)
```

Append:

```python
class BrokerOrderEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def record_from_broker_result(
        self,
        *,
        run_id: int | None,
        order_id: int | None,
        request: BrokerOrderRequest,
        result: BrokerOrderResult,
        created_at: datetime | date,
    ) -> BrokerOrderEventORM:
        request_payload = _broker_request_payload(request)
        result_payload = _broker_result_payload(result)
        row = BrokerOrderEventORM(
            run_id=run_id,
            order_id=order_id,
            broker_mode=result.mode.value,
            client_order_id=request.client_order_id,
            broker_order_id=result.broker_order_id,
            status=result.status.value,
            accepted=result.accepted,
            request_payload=_json_dumps(request_payload),
            result_payload=_json_dumps(result_payload),
            message=result.message[:512],
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_for_order(self, order_id: int) -> list[BrokerOrderEventORM]:
        return list(
            self.session.scalars(
                select(BrokerOrderEventORM)
                .where(BrokerOrderEventORM.order_id == order_id)
                .order_by(BrokerOrderEventORM.id)
            ).all()
        )

    def list_for_run(self, run_id: int) -> list[BrokerOrderEventORM]:
        return list(
            self.session.scalars(
                select(BrokerOrderEventORM)
                .where(BrokerOrderEventORM.run_id == run_id)
                .order_by(BrokerOrderEventORM.id)
            ).all()
        )

    def get(self, event_id: int) -> BrokerOrderEventORM | None:
        return self.session.get(BrokerOrderEventORM, event_id)
```

Add serialization helpers:

```python
def _broker_request_payload(request: BrokerOrderRequest) -> dict:
    return {
        "client_order_id": request.client_order_id,
        "instrument_id": request.instrument_id,
        "symbol": request.symbol,
        "side": request.side.value,
        "order_type": request.order_type.value,
        "quantity": request.quantity,
        "limit_price": request.limit_price,
        "submitted_at": request.submitted_at,
        "reason": request.reason,
    }


def _broker_result_payload(result: BrokerOrderResult) -> dict:
    payload = {
        "broker_order_id": result.broker_order_id,
        "status": result.status.value,
        "mode": result.mode.value,
        "accepted": result.accepted,
        "message": result.message[:512],
        "has_fill": result.fill is not None,
    }
    if result.fill is not None:
        payload["fill"] = {
            "instrument_id": result.fill.instrument_id,
            "symbol": result.fill.symbol,
            "side": result.fill.side.value,
            "quantity": result.fill.quantity,
            "price": result.fill.price,
            "commission": result.fill.commission,
            "slippage": result.fill.slippage,
            "filled_at": result.fill.filled_at,
        }
    return payload
```

- [ ] **Step 6: Add migration**

Create `migrations/versions/20260623_0006_add_broker_order_events.py`:

```python
"""add broker order events

Revision ID: 20260623_0006
Revises: 20260623_0005
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0006"
down_revision = "20260623_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("paper_runs.id"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("paper_orders.id"), nullable=True),
        sa.Column("broker_mode", sa.String(length=32), nullable=False),
        sa.Column("client_order_id", sa.String(length=128), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("request_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("message", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_broker_order_events_run_id", "broker_order_events", ["run_id"])
    op.create_index("ix_broker_order_events_order_id", "broker_order_events", ["order_id"])
    op.create_index("ix_broker_order_events_broker_mode", "broker_order_events", ["broker_mode"])
    op.create_index("ix_broker_order_events_client_order_id", "broker_order_events", ["client_order_id"])
    op.create_index("ix_broker_order_events_broker_order_id", "broker_order_events", ["broker_order_id"])
    op.create_index("ix_broker_order_events_status", "broker_order_events", ["status"])
    op.create_index("ix_broker_order_events_accepted", "broker_order_events", ["accepted"])
    op.create_index("ix_broker_order_events_created_at", "broker_order_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_broker_order_events_created_at", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_accepted", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_status", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_broker_order_id", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_client_order_id", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_broker_mode", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_order_id", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_run_id", table_name="broker_order_events")
    op.drop_table("broker_order_events")
```

- [ ] **Step 7: Verify task**

Run:

```bash
python -m pytest tests/integration/test_migrations.py tests/integration/test_broker_order_events_repository.py -q
python -m py_compile src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260623_0006_add_broker_order_events.py
```

Expected: PASS.

- [ ] **Step 8: Spec and quality review**

Spec review:

- Confirm migration creates `broker_order_events`.
- Confirm repository records normalized request/result payloads.
- Confirm no raw secrets or unbounded raw broker responses are persisted.

Quality review:

- Confirm append-only repository has focused query methods.
- Confirm payload serialization handles Decimal/date/enums.
- Confirm message is capped to 512 chars.

- [ ] **Step 9: Commit**

```bash
git add tests/integration/test_migrations.py tests/integration/test_broker_order_events_repository.py src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260623_0006_add_broker_order_events.py
git commit -m "feat: add broker order audit storage"
```

## Task 2: Paper Engine Audit Integration

**Files:**

- Modify: `tests/integration/test_paper_engine.py`
- Modify: `src/quant_trading/paper/engine.py`

- [ ] **Step 1: Write failing paper engine audit assertions**

Modify `tests/integration/test_paper_engine.py`.

In `test_paper_tick_persists_approved_buy_and_is_idempotent()`, after loading `risk_decision`, also load:

```python
        broker_events = BrokerOrderEventRepository(session).list_for_run(run_id)
```

Assert:

```python
    assert len(broker_events) == 1
    assert broker_events[0].broker_mode == "simulated"
    assert broker_events[0].status == "filled"
    assert broker_events[0].accepted is True
    assert json.loads(broker_events[0].result_payload)["has_fill"] is True
```

In `test_paper_tick_with_dry_run_broker_records_order_without_fill_or_position()`, load:

```python
        broker_events = BrokerOrderEventRepository(session).list_for_run(run_id)
```

Assert:

```python
    assert len(broker_events) == 1
    assert broker_events[0].broker_mode == "dry_run"
    assert broker_events[0].status == "submitted"
    assert broker_events[0].accepted is True
    assert json.loads(broker_events[0].result_payload)["has_fill"] is False
```

Add imports at top:

```python
import json
from quant_trading.storage.repositories import BrokerOrderEventRepository
```

or local imports if that matches the file style.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/integration/test_paper_engine.py::test_paper_tick_persists_approved_buy_and_is_idempotent tests/integration/test_paper_engine.py::test_paper_tick_with_dry_run_broker_records_order_without_fill_or_position -q
```

Expected: FAIL because paper engine does not record broker events yet.

- [ ] **Step 3: Record broker audit from paper engine**

Modify `src/quant_trading/paper/engine.py` imports:

```python
from quant_trading.storage.repositories import BrokerOrderEventRepository, MarketDataRepository
```

After:

```python
                broker_result = self.broker.submit_order(request, latest)
```

add:

```python
                BrokerOrderEventRepository(session).record_from_broker_result(
                    run_id=run.id,
                    order_id=order.id,
                    request=request,
                    result=broker_result,
                    created_at=latest.timestamp,
                )
```

- [ ] **Step 4: Verify task**

Run:

```bash
python -m pytest tests/integration/test_paper_engine.py::test_paper_tick_persists_approved_buy_and_is_idempotent tests/integration/test_paper_engine.py::test_paper_tick_with_dry_run_broker_records_order_without_fill_or_position -q
python -m py_compile src/quant_trading/paper/engine.py
```

Expected: PASS.

- [ ] **Step 5: Spec and quality review**

Spec review:

- Confirm simulated and dry-run paper ticks write broker audit events.
- Confirm dry-run still creates no fill and no position.
- Confirm audit is recorded in the same session as paper tick.

Quality review:

- Confirm paper engine still delegates serialization to repository.
- Confirm no broker credentials or raw external payloads are introduced.
- Confirm existing idempotent no-op tick does not write a new broker event.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_paper_engine.py src/quant_trading/paper/engine.py
git commit -m "feat: audit paper broker submissions"
```

## Task 3: Documentation And Final Verification

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Update README**

In `Broker Adapter Safety Boundary`, add:

```markdown
Broker submissions from paper trading are persisted to `broker_order_events`. Each row stores normalized request/result metadata such as client order id, broker order id, mode, status, accepted flag, and a capped message. The audit payload intentionally excludes credentials, API tokens, and raw unbounded broker responses.
```

- [ ] **Step 2: README grep check**

Run:

```bash
rg -n "broker_order_events|normalized request/result|excludes credentials|Broker Adapter Safety Boundary" README.md
```

Expected: all safety claims appear.

- [ ] **Step 3: Final verification**

Run:

```bash
python -m pytest -q
python -m py_compile src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py src/quant_trading/paper/engine.py migrations/versions/20260623_0006_add_broker_order_events.py
docker compose config
git diff --check
git status --short --branch
```

Expected: full test suite PASS; py_compile PASS; compose config exits 0; diff check exits 0; git status shows only intended README changes before final commit.

- [ ] **Step 4: Spec and quality review**

Spec review:

- Confirm README documents broker order audit.
- Confirm docs state credentials/raw unbounded responses are excluded.

Quality review:

- Confirm docs do not imply live broker support.
- Confirm docs align with actual table name.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document broker order audit"
```

## Plan Self-Review

- Spec coverage: migration, ORM, repository, paper engine integration, simulated/dry-run tests, README, and final verification are covered.
- Placeholder scan: no TBD/TODO/fill-in placeholders are used.
- Type consistency: table/model/repository consistently use `broker_order_events`, `BrokerOrderEventORM`, and `BrokerOrderEventRepository`.

Plan complete and saved to `docs/superpowers/plans/2026-06-23-quant-trading-broker-order-audit.md`.

Execution recommendation: use inline execution with `superpowers:executing-plans` because this stage is tightly scoped across schema, repository, and paper engine.
