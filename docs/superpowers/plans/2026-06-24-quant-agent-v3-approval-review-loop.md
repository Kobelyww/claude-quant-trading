# Quant Agent v3 Approval And Backtest Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an audited research loop from a validated `strategy_idea` candidate through human approval, backtest job submission, backtest result linking, and a research-only `backtest_review` recommendation.

**Architecture:** Add `agent_candidate_reviews` as the durable operator decision record, with a focused candidate-review service owning state transitions and job submission. Add a `backtest_review` agent that reads persisted candidate and backtest artifacts, produces bounded research-only JSON, and plugs into the existing `job_runs` and `agent_runs` audit paths.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, pytest, existing inline/RQ job runtime, existing `FakeLLMClient`.

---

## Branch And Scope Notes

- Working directory: `/Users/haobowang/Desktop/Code file/Python/LLM-Study/quant-trading/.worktrees/quant-agent-v1`
- Working branch: `codex/quant-agent-v3-approval-review-loop`
- Design spec: `docs/superpowers/specs/2026-06-24-quant-agent-v3-approval-review-loop-design.md`
- This branch is stacked on the local v2 branch content. Before final push, try syncing with remote `main` again because previous SSH and HTTPS fetch attempts timed out.
- This plan does not add dashboard UI, generated strategy code execution, arbitrary strategy templates, paper-run creation, broker calls, or real-money execution.

## File Structure

- Modify: `src/quant_trading/storage/models.py`
  - Add `AgentCandidateReviewORM`.
  - Keep payload columns as JSON strings to match existing `agent_runs` and `job_runs` patterns.
- Modify: `src/quant_trading/storage/repositories.py`
  - Add `AgentCandidateReviewRepository`.
  - Keep JSON encoding outside the repository except for existing local helper reuse.
- Create: `migrations/versions/20260624_0008_add_agent_candidate_reviews.py`
  - Alembic revision after `20260624_0007`.
- Modify: `tests/integration/test_migrations.py`
  - Assert migration creates the candidate review table and columns.
- Create: `tests/integration/test_agent_candidate_reviews_repository.py`
  - Repository lifecycle coverage.
- Create: `src/quant_trading/agents/candidate_reviews.py`
  - Candidate approval, rejection, refresh, payload serialization, and state-transition exceptions.
- Create: `tests/integration/test_agent_candidate_approval_service.py`
  - Approval/rejection service coverage with real inline backtest jobs.
- Create: `src/quant_trading/api/routes/agent_candidates.py`
  - Read, approve, reject, and refresh HTTP APIs.
- Modify: `src/quant_trading/api/main.py`
  - Include the new router.
- Create: `tests/integration/test_agent_candidates_api.py`
  - HTTP coverage for the candidate review APIs.
- Create: `src/quant_trading/agents/backtest_review.py`
  - Backtest review context loading, prompt building, response parsing, and conservative metrics.
- Create: `tests/unit/test_backtest_review_agent.py`
  - Prompt safety and parser coverage.
- Modify: `src/quant_trading/agents/models.py`
  - Add `AGENT_BACKTEST_REVIEW` and `BacktestReviewRequest`.
- Modify: `src/quant_trading/agents/service.py`
  - Add `run_backtest_review_agent()`.
- Modify: `src/quant_trading/jobs/runtime.py`
  - Add `JOB_AGENT_BACKTEST_REVIEW` and runtime dispatch.
- Modify: `src/quant_trading/api/routes/jobs.py`
  - Add `POST /jobs/agents/backtest-review`.
- Modify: `tests/integration/test_agents_jobs.py`
  - Add review-job integration and safety invariant coverage.
- Modify: `README.md`
  - Document the v3 operator workflow and safety boundaries.

## Review Protocol For Every Implementation Task

Each implementation task must finish with both checks before commit:

1. **Spec review:** Compare the task against `docs/superpowers/specs/2026-06-24-quant-agent-v3-approval-review-loop-design.md`. Confirm every changed behavior is in scope and no non-goal behavior slipped in.
2. **Quality review:** Check state names, JSON shapes, exception/API mappings, migrations, secrets handling, broker/paper isolation, and test coverage.

Record the review result in the task notes before committing. If either review fails, fix the issue before moving to the next task.

---

### Task 1: Candidate Review Storage And Migration

**Files:**
- Modify: `src/quant_trading/storage/models.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `migrations/versions/20260624_0008_add_agent_candidate_reviews.py`
- Modify: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_agent_candidate_reviews_repository.py`

- [ ] **Step 1: Write failing repository tests**

Create `tests/integration/test_agent_candidate_reviews_repository.py`:

```python
import json
from datetime import datetime

from sqlalchemy import select

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import AgentCandidateReviewORM, AgentRunORM
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentRunRepository,
)


def _create_source_agent_run(session):
    row = AgentRunRepository(session).create_running(
        agent_type="strategy_idea",
        symbol="000001",
        model_name="fake-llm",
        request_payload="{}",
        job_run_id=None,
        started_at=datetime(2026, 6, 24, 9, 0, 0),
    )
    AgentRunRepository(session).mark_succeeded(
        row,
        metrics_payload="{}",
        result_payload=json.dumps(
            {
                "parsed": True,
                "validation_status": "passed",
                "candidate_payload": {
                    "strategy_name": "ma_cross",
                    "symbol": "000001",
                    "parameters": {
                        "short_window": 5,
                        "long_window": 20,
                        "order_size": 100,
                    },
                    "requires_human_approval": True,
                },
                "backtest_request_payload": {
                    "job_type": "backtest_ma_cross",
                    "payload": {
                        "symbol": "000001",
                        "short_window": 5,
                        "long_window": 20,
                        "order_size": 100,
                        "initial_cash": "100000",
                    },
                },
                "requires_human_approval": True,
            },
            sort_keys=True,
        ),
        finished_at=datetime(2026, 6, 24, 9, 0, 1),
        duration_ms=1,
    )
    return row


def test_candidate_review_repository_lifecycle():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    now = datetime(2026, 6, 24, 9, 0, 0)

    with session_scope(engine) as session:
        source = _create_source_agent_run(session)
        repo = AgentCandidateReviewRepository(session)
        review = repo.create_decision(
            source_agent_run_id=source.id,
            status="approved",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload=json.dumps({"strategy_name": "ma_cross"}, sort_keys=True),
            backtest_request_payload=json.dumps(
                {"job_type": "backtest_ma_cross", "payload": {"symbol": "000001"}},
                sort_keys=True,
            ),
            operator="local",
            operator_note="approved for research backtest",
            decided_at=now,
            created_at=now,
        )
        review_id = review.id
        repo.mark_backtest_submitted(review, backtest_job_run_id=7, updated_at=now)
        repo.mark_backtest_succeeded(review, backtest_run_id=11, updated_at=now)
        repo.mark_review_requested(review, review_agent_run_id=13, updated_at=now)
        repo.mark_review_succeeded(review, review_agent_run_id=13, updated_at=now)

    with session_scope(engine) as session:
        review = AgentCandidateReviewRepository(session).get(review_id)
        assert review is not None
        assert review.source_agent_run_id == 1
        assert review.status == "review_succeeded"
        assert review.symbol == "000001"
        assert review.strategy_name == "ma_cross"
        assert review.operator == "local"
        assert review.operator_note == "approved for research backtest"
        assert review.backtest_job_run_id == 7
        assert review.backtest_run_id == 11
        assert review.review_agent_run_id == 13
        assert review.error_message is None
        assert AgentCandidateReviewRepository(session).get_by_source_agent_run_id(1).id == review_id
        assert [row.id for row in AgentCandidateReviewRepository(session).list_recent()] == [review_id]


def test_candidate_review_source_agent_run_is_unique():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    now = datetime(2026, 6, 24, 9, 0, 0)

    with session_scope(engine) as session:
        source = _create_source_agent_run(session)
        source_id = source.id
        repo = AgentCandidateReviewRepository(session)
        repo.create_decision(
            source_agent_run_id=source_id,
            status="rejected",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload="{}",
            backtest_request_payload="{}",
            operator="local",
            operator_note="insufficient thesis",
            decided_at=now,
            created_at=now,
        )

    with session_scope(engine) as session:
        repo = AgentCandidateReviewRepository(session)
        try:
            repo.create_decision(
                source_agent_run_id=source_id,
                status="approved",
                symbol="000001",
                strategy_name="ma_cross",
                candidate_payload="{}",
                backtest_request_payload="{}",
                operator="local",
                operator_note="duplicate",
                decided_at=now,
                created_at=now,
            )
        except Exception as exc:
            session.rollback()
            assert "UNIQUE" in str(exc).upper() or "unique" in exc.__class__.__name__.lower()
        else:
            raise AssertionError("duplicate candidate review should violate unique source")

    with session_scope(engine) as session:
        rows = session.scalars(select(AgentCandidateReviewORM)).all()
        assert len(rows) == 1
        assert session.get(AgentRunORM, 1) is not None
```

- [ ] **Step 2: Run repository tests to verify failure**

Run:

```bash
pytest tests/integration/test_agent_candidate_reviews_repository.py -q
```

Expected: FAIL because `AgentCandidateReviewORM` and `AgentCandidateReviewRepository` do not exist.

- [ ] **Step 3: Add ORM model**

In `src/quant_trading/storage/models.py`, append this class after `AgentRunORM`:

```python
class AgentCandidateReviewORM(Base):
    __tablename__ = "agent_candidate_reviews"
    __table_args__ = (
        UniqueConstraint(
            "source_agent_run_id",
            name="uq_agent_candidate_reviews_source_agent_run_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_agent_run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), index=True)
    candidate_payload: Mapped[str] = mapped_column(Text, default="{}")
    backtest_request_payload: Mapped[str] = mapped_column(Text, default="{}")
    operator: Mapped[str] = mapped_column(String(128), default="")
    operator_note: Mapped[str] = mapped_column(Text, default="")
    backtest_job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"),
        nullable=True,
        index=True,
    )
    backtest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("backtest_runs.id"),
        nullable=True,
        index=True,
    )
    review_agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id"),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Add repository**

In `src/quant_trading/storage/repositories.py`, add `AgentCandidateReviewORM` to the model import list, then append:

```python
class AgentCandidateReviewRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_decision(
        self,
        *,
        source_agent_run_id: int,
        status: str,
        symbol: str,
        strategy_name: str,
        candidate_payload: str,
        backtest_request_payload: str,
        operator: str,
        operator_note: str,
        decided_at: datetime,
        created_at: datetime,
    ) -> AgentCandidateReviewORM:
        row = AgentCandidateReviewORM(
            source_agent_run_id=source_agent_run_id,
            status=status,
            symbol=symbol,
            strategy_name=strategy_name,
            candidate_payload=candidate_payload,
            backtest_request_payload=backtest_request_payload,
            operator=operator,
            operator_note=operator_note,
            decided_at=decided_at,
            created_at=created_at,
            updated_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_backtest_submitted(
        self,
        row: AgentCandidateReviewORM,
        *,
        backtest_job_run_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "backtest_submitted"
        row.backtest_job_run_id = backtest_job_run_id
        row.error_message = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_backtest_succeeded(
        self,
        row: AgentCandidateReviewORM,
        *,
        backtest_run_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "backtest_succeeded"
        row.backtest_run_id = backtest_run_id
        row.error_message = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_backtest_failed(
        self,
        row: AgentCandidateReviewORM,
        *,
        error_message: str,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "backtest_failed"
        row.error_message = error_message[:1000]
        row.updated_at = updated_at
        self.session.flush()
        return row

    def update_rejection(
        self,
        row: AgentCandidateReviewORM,
        *,
        candidate_payload: str,
        backtest_request_payload: str,
        operator: str,
        operator_note: str,
        decided_at: datetime,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "rejected"
        row.candidate_payload = candidate_payload
        row.backtest_request_payload = backtest_request_payload
        row.operator = operator
        row.operator_note = operator_note
        row.decided_at = decided_at
        row.error_message = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_review_requested(
        self,
        row: AgentCandidateReviewORM,
        *,
        review_agent_run_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "review_requested"
        row.review_agent_run_id = review_agent_run_id
        row.error_message = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_review_succeeded(
        self,
        row: AgentCandidateReviewORM,
        *,
        review_agent_run_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "review_succeeded"
        row.review_agent_run_id = review_agent_run_id
        row.error_message = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_review_failed(
        self,
        row: AgentCandidateReviewORM,
        *,
        error_message: str,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "review_failed"
        row.error_message = error_message[:1000]
        row.updated_at = updated_at
        self.session.flush()
        return row

    def get(self, candidate_review_id: int) -> AgentCandidateReviewORM | None:
        return self.session.get(AgentCandidateReviewORM, candidate_review_id)

    def get_by_source_agent_run_id(self, source_agent_run_id: int) -> AgentCandidateReviewORM | None:
        return self.session.scalar(
            select(AgentCandidateReviewORM).where(
                AgentCandidateReviewORM.source_agent_run_id == source_agent_run_id
            )
        )

    def list_recent(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[AgentCandidateReviewORM]:
        statement = select(AgentCandidateReviewORM).order_by(
            AgentCandidateReviewORM.id.desc()
        ).limit(limit)
        if status:
            statement = statement.where(AgentCandidateReviewORM.status == status)
        if symbol:
            statement = statement.where(AgentCandidateReviewORM.symbol == symbol)
        return list(self.session.scalars(statement).all())
```

- [ ] **Step 5: Add Alembic migration**

Create `migrations/versions/20260624_0008_add_agent_candidate_reviews.py`:

```python
"""add agent candidate reviews

Revision ID: 20260624_0008
Revises: 20260624_0007
Create Date: 2026-06-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260624_0008"
down_revision = "20260624_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_candidate_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_agent_run_id", sa.Integer(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("candidate_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("backtest_request_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("operator", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("operator_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("backtest_job_run_id", sa.Integer(), sa.ForeignKey("job_runs.id"), nullable=True),
        sa.Column("backtest_run_id", sa.Integer(), sa.ForeignKey("backtest_runs.id"), nullable=True),
        sa.Column("review_agent_run_id", sa.Integer(), sa.ForeignKey("agent_runs.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "source_agent_run_id",
            name="uq_agent_candidate_reviews_source_agent_run_id",
        ),
    )
    op.create_index(
        "ix_agent_candidate_reviews_source_agent_run_id",
        "agent_candidate_reviews",
        ["source_agent_run_id"],
    )
    op.create_index("ix_agent_candidate_reviews_status", "agent_candidate_reviews", ["status"])
    op.create_index("ix_agent_candidate_reviews_symbol", "agent_candidate_reviews", ["symbol"])
    op.create_index(
        "ix_agent_candidate_reviews_strategy_name",
        "agent_candidate_reviews",
        ["strategy_name"],
    )
    op.create_index(
        "ix_agent_candidate_reviews_backtest_job_run_id",
        "agent_candidate_reviews",
        ["backtest_job_run_id"],
    )
    op.create_index(
        "ix_agent_candidate_reviews_backtest_run_id",
        "agent_candidate_reviews",
        ["backtest_run_id"],
    )
    op.create_index(
        "ix_agent_candidate_reviews_review_agent_run_id",
        "agent_candidate_reviews",
        ["review_agent_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_candidate_reviews_review_agent_run_id", table_name="agent_candidate_reviews")
    op.drop_index("ix_agent_candidate_reviews_backtest_run_id", table_name="agent_candidate_reviews")
    op.drop_index("ix_agent_candidate_reviews_backtest_job_run_id", table_name="agent_candidate_reviews")
    op.drop_index("ix_agent_candidate_reviews_strategy_name", table_name="agent_candidate_reviews")
    op.drop_index("ix_agent_candidate_reviews_symbol", table_name="agent_candidate_reviews")
    op.drop_index("ix_agent_candidate_reviews_status", table_name="agent_candidate_reviews")
    op.drop_index("ix_agent_candidate_reviews_source_agent_run_id", table_name="agent_candidate_reviews")
    op.drop_table("agent_candidate_reviews")
```

- [ ] **Step 6: Extend migration test**

In `tests/integration/test_migrations.py`, add these assertions after the existing `agent_runs` assertions:

```python
    assert "agent_candidate_reviews" in tables

    candidate_review_columns = {
        column["name"] for column in inspector.get_columns("agent_candidate_reviews")
    }
    assert {
        "id",
        "source_agent_run_id",
        "status",
        "symbol",
        "strategy_name",
        "candidate_payload",
        "backtest_request_payload",
        "operator",
        "operator_note",
        "backtest_job_run_id",
        "backtest_run_id",
        "review_agent_run_id",
        "error_message",
        "created_at",
        "updated_at",
        "decided_at",
    } <= candidate_review_columns
```

- [ ] **Step 7: Run storage and migration tests**

Run:

```bash
pytest tests/integration/test_agent_candidate_reviews_repository.py tests/integration/test_migrations.py -q
```

Expected: PASS.

- [ ] **Step 8: Run task reviews**

Spec review:

```text
Task 1 adds the required agent_candidate_reviews table, source_agent_run_id uniqueness, create_all coverage via ORM, and Alembic coverage. It does not add approval, jobs, agents, paper runs, broker calls, or UI.
```

Quality review:

```text
Repository methods keep state transitions explicit, payloads bounded to text columns, and indexes align with lookup paths. Migration down_revision follows 20260624_0007.
```

- [ ] **Step 9: Commit**

Run:

```bash
git add src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260624_0008_add_agent_candidate_reviews.py tests/integration/test_migrations.py tests/integration/test_agent_candidate_reviews_repository.py
git commit -m "feat: add agent candidate review storage"
```

---

### Task 2: Candidate Approval And Rejection Service

**Files:**
- Create: `src/quant_trading/agents/candidate_reviews.py`
- Create: `tests/integration/test_agent_candidate_approval_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/integration/test_agent_candidate_approval_service.py`:

```python
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from quant_trading.agents.candidate_reviews import (
    CandidateReviewConflictError,
    CandidateReviewValidationError,
    approve_strategy_candidate,
    reject_strategy_candidate,
)
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    AgentRunORM,
    BacktestRunORM,
    BrokerOrderEventORM,
    JobRunORM,
    PaperRunORM,
)
from quant_trading.storage.repositories import AgentRunRepository


def _valid_strategy_result(**overrides):
    payload = {
        "agent_type": "strategy_idea",
        "parsed": True,
        "validation_status": "passed",
        "candidate_payload": {
            "strategy_name": "ma_cross",
            "symbol": "000001",
            "parameters": {
                "short_window": 5,
                "long_window": 20,
                "order_size": 100,
            },
            "requires_human_approval": True,
        },
        "backtest_request_payload": {
            "job_type": "backtest_ma_cross",
            "payload": {
                "symbol": "000001",
                "short_window": 5,
                "long_window": 20,
                "order_size": 100,
                "initial_cash": "100000",
            },
        },
        "requires_human_approval": True,
    }
    payload.update(overrides)
    return payload


def _create_agent_run(engine, *, agent_type="strategy_idea", status="succeeded", result_payload=None):
    result_payload = result_payload if result_payload is not None else _valid_strategy_result()
    with session_scope(engine) as session:
        row = AgentRunRepository(session).create_running(
            agent_type=agent_type,
            symbol="000001",
            model_name="fake-llm",
            request_payload="{}",
            job_run_id=None,
            started_at=datetime(2026, 6, 24, 9, 0, 0),
        )
        if status == "succeeded":
            AgentRunRepository(session).mark_succeeded(
                row,
                metrics_payload="{}",
                result_payload=json.dumps(result_payload, sort_keys=True),
                finished_at=datetime(2026, 6, 24, 9, 0, 1),
                duration_ms=1,
            )
        elif status == "failed":
            AgentRunRepository(session).mark_failed(
                row,
                "llm failed",
                finished_at=datetime(2026, 6, 24, 9, 0, 1),
                duration_ms=1,
            )
        else:
            raise AssertionError(f"unsupported test status: {status}")
        return row.id


def test_approve_strategy_candidate_submits_exact_backtest_job_and_links_inline_result(
    legacy_sqlite_db: Path,
):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)
    agent_run_id = _create_agent_run(engine)

    review = approve_strategy_candidate(
        engine,
        source_agent_run_id=agent_run_id,
        operator="local",
        note="approved for research backtest",
        settings=AppSettings(job_executor="inline"),
    )

    assert review.status == "backtest_succeeded"
    assert review.source_agent_run_id == agent_run_id
    assert review.backtest_job_run_id == 1
    assert review.backtest_run_id == 1
    assert review.operator == "local"
    assert json.loads(review.backtest_request_payload)["payload"]["symbol"] == "000001"
    with session_scope(engine) as session:
        job = session.get(JobRunORM, review.backtest_job_run_id)
        assert job is not None
        assert job.job_type == "backtest_ma_cross"
        assert json.loads(job.request_payload) == {
            "symbol": "000001",
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
            "initial_cash": "100000",
        }
        assert session.query(BacktestRunORM).count() == 1
        assert session.query(PaperRunORM).count() == 0
        assert session.query(BrokerOrderEventORM).count() == 0


def test_approve_strategy_candidate_records_backtest_failure_without_data():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    agent_run_id = _create_agent_run(engine)

    review = approve_strategy_candidate(
        engine,
        source_agent_run_id=agent_run_id,
        operator="local",
        note="approved for research backtest",
        settings=AppSettings(job_executor="inline"),
    )

    assert review.status == "backtest_failed"
    assert review.backtest_job_run_id == 1
    assert review.backtest_run_id is None
    assert "no market bars found for symbol: 000001" in review.error_message


def test_duplicate_approval_conflicts_and_does_not_submit_second_job(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)
    agent_run_id = _create_agent_run(engine)
    approve_strategy_candidate(
        engine,
        source_agent_run_id=agent_run_id,
        operator="local",
        note="approved for research backtest",
        settings=AppSettings(job_executor="inline"),
    )

    with pytest.raises(CandidateReviewConflictError, match="candidate already submitted"):
        approve_strategy_candidate(
            engine,
            source_agent_run_id=agent_run_id,
            operator="local",
            note="duplicate",
            settings=AppSettings(job_executor="inline"),
        )

    with session_scope(engine) as session:
        assert session.query(JobRunORM).count() == 1
        assert session.query(AgentCandidateReviewORM).count() == 1


def test_reject_strategy_candidate_creates_terminal_review_and_no_job():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    agent_run_id = _create_agent_run(engine)

    review = reject_strategy_candidate(
        engine,
        source_agent_run_id=agent_run_id,
        operator="local",
        note="insufficient thesis",
    )

    assert review.status == "rejected"
    assert review.operator_note == "insufficient thesis"
    assert review.backtest_job_run_id is None
    assert review.backtest_run_id is None
    with session_scope(engine) as session:
        assert session.query(JobRunORM).count() == 0
        assert session.query(BacktestRunORM).count() == 0
        assert session.query(PaperRunORM).count() == 0
        assert session.query(BrokerOrderEventORM).count() == 0


def test_reject_strategy_candidate_updates_existing_rejected_review():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    agent_run_id = _create_agent_run(engine)
    first = reject_strategy_candidate(
        engine,
        source_agent_run_id=agent_run_id,
        operator="local",
        note="insufficient thesis",
    )

    second = reject_strategy_candidate(
        engine,
        source_agent_run_id=agent_run_id,
        operator="lead",
        note="still insufficient after review",
    )

    assert second.id == first.id
    assert second.status == "rejected"
    assert second.operator == "lead"
    assert second.operator_note == "still insufficient after review"
    with session_scope(engine) as session:
        assert session.query(JobRunORM).count() == 0
        assert session.query(AgentCandidateReviewORM).count() == 1


def test_reject_after_approval_conflicts(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)
    agent_run_id = _create_agent_run(engine)
    approve_strategy_candidate(
        engine,
        source_agent_run_id=agent_run_id,
        operator="local",
        note="approved for research backtest",
        settings=AppSettings(job_executor="inline"),
    )

    with pytest.raises(CandidateReviewConflictError, match="cannot reject candidate after approval"):
        reject_strategy_candidate(
            engine,
            source_agent_run_id=agent_run_id,
            operator="local",
            note="changed mind",
        )


@pytest.mark.parametrize(
    ("agent_type", "status", "result_payload", "message"),
    [
        ("market_analysis", "succeeded", _valid_strategy_result(), "source agent run is not a strategy idea"),
        ("strategy_idea", "failed", _valid_strategy_result(), "source agent run has not succeeded"),
        (
            "strategy_idea",
            "succeeded",
            _valid_strategy_result(parsed=False),
            "strategy candidate was not parsed",
        ),
        (
            "strategy_idea",
            "succeeded",
            _valid_strategy_result(validation_status="failed"),
            "candidate validation did not pass",
        ),
        (
            "strategy_idea",
            "succeeded",
            _valid_strategy_result(backtest_request_payload={"job_type": "unknown", "payload": {}}),
            "unsupported backtest job type",
        ),
    ],
)
def test_approval_rejects_invalid_source_agent_runs(
    agent_type,
    status,
    result_payload,
    message,
):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    agent_run_id = _create_agent_run(
        engine,
        agent_type=agent_type,
        status=status,
        result_payload=result_payload,
    )

    with pytest.raises(CandidateReviewValidationError, match=message):
        approve_strategy_candidate(
            engine,
            source_agent_run_id=agent_run_id,
            operator="local",
            note="approved",
            settings=AppSettings(job_executor="inline"),
        )

    with session_scope(engine) as session:
        assert session.scalar(select(AgentCandidateReviewORM)) is None
        assert session.query(JobRunORM).count() == 0
```

- [ ] **Step 2: Run service tests to verify failure**

Run:

```bash
pytest tests/integration/test_agent_candidate_approval_service.py -q
```

Expected: FAIL because `quant_trading.agents.candidate_reviews` does not exist.

- [ ] **Step 3: Implement candidate review service exceptions and helpers**

Create `src/quant_trading/agents/candidate_reviews.py` with these top-level constants and exceptions:

```python
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import Engine

from quant_trading.agents.models import AGENT_STRATEGY_IDEA
from quant_trading.config import AppSettings
from quant_trading.jobs.queue import make_queue
from quant_trading.jobs.runtime import BACKTEST_MA_CROSS
from quant_trading.jobs.service import QueueLike, submit_job_run
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import AgentCandidateReviewORM, AgentRunORM
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentRunRepository,
    JobRunRepository,
)

STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_BACKTEST_SUBMITTED = "backtest_submitted"
STATUS_BACKTEST_SUCCEEDED = "backtest_succeeded"
STATUS_BACKTEST_FAILED = "backtest_failed"
STATUS_REVIEW_REQUESTED = "review_requested"
STATUS_REVIEW_SUCCEEDED = "review_succeeded"
STATUS_REVIEW_FAILED = "review_failed"

ERROR_MAX_CHARS = 1000
OPERATOR_MAX_CHARS = 128
NOTE_MAX_CHARS = 4000


class CandidateReviewError(ValueError):
    pass


class CandidateReviewNotFoundError(CandidateReviewError):
    pass


class CandidateReviewConflictError(CandidateReviewError):
    pass


class CandidateReviewValidationError(CandidateReviewError):
    pass


def candidate_review_payload(row: AgentCandidateReviewORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_agent_run_id": row.source_agent_run_id,
        "status": row.status,
        "symbol": row.symbol,
        "strategy_name": row.strategy_name,
        "candidate_payload": _json_loads(row.candidate_payload),
        "backtest_request_payload": _json_loads(row.backtest_request_payload),
        "operator": row.operator,
        "operator_note": row.operator_note,
        "backtest_job_run_id": row.backtest_job_run_id,
        "backtest_run_id": row.backtest_run_id,
        "review_agent_run_id": row.review_agent_run_id,
        "error_message": row.error_message,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "decided_at": _iso(row.decided_at),
    }
```

- [ ] **Step 4: Implement approval and rejection functions**

Add these functions to `candidate_reviews.py`:

```python
def approve_strategy_candidate(
    engine: Engine,
    *,
    source_agent_run_id: int,
    operator: str,
    note: str,
    settings: AppSettings,
    queue_factory: Callable[[str], QueueLike] = make_queue,
) -> AgentCandidateReviewORM:
    now = _utcnow()
    operator = _clean_operator(operator)
    note = _clean_note(note)
    with session_scope(engine) as session:
        agent_run = AgentRunRepository(session).get(source_agent_run_id)
        if agent_run is None:
            raise CandidateReviewNotFoundError("source agent run not found")
        existing = AgentCandidateReviewRepository(session).get_by_source_agent_run_id(
            source_agent_run_id
        )
        if existing is not None:
            _raise_existing_approval_conflict(existing)
        candidate = _validated_candidate_from_agent_run(agent_run)
        review = AgentCandidateReviewRepository(session).create_decision(
            source_agent_run_id=agent_run.id,
            status=STATUS_APPROVED,
            symbol=candidate["symbol"],
            strategy_name=candidate["strategy_name"],
            candidate_payload=_json_dumps(candidate["candidate_payload"]),
            backtest_request_payload=_json_dumps(candidate["backtest_request_payload"]),
            operator=operator,
            operator_note=note,
            decided_at=now,
            created_at=now,
        )
        review_id = review.id

    backtest_request_payload = candidate["backtest_request_payload"]
    job = submit_job_run(
        engine,
        settings,
        BACKTEST_MA_CROSS,
        backtest_request_payload["payload"],
        queue_factory,
    )
    with session_scope(engine) as session:
        repo = AgentCandidateReviewRepository(session)
        review = repo.get(review_id)
        if review is None:
            raise CandidateReviewNotFoundError("candidate review not found after approval")
        repo.mark_backtest_submitted(
            review,
            backtest_job_run_id=job.id,
            updated_at=_utcnow(),
        )
        _refresh_backtest_status_from_job_row(session, review)
        session.expunge(review)
        return review


def reject_strategy_candidate(
    engine: Engine,
    *,
    source_agent_run_id: int,
    operator: str,
    note: str,
) -> AgentCandidateReviewORM:
    now = _utcnow()
    operator = _clean_operator(operator)
    note = _clean_note(note)
    with session_scope(engine) as session:
        agent_run = AgentRunRepository(session).get(source_agent_run_id)
        if agent_run is None:
            raise CandidateReviewNotFoundError("source agent run not found")
        existing = AgentCandidateReviewRepository(session).get_by_source_agent_run_id(
            source_agent_run_id
        )
        if existing is not None and existing.status != STATUS_REJECTED:
            raise CandidateReviewConflictError("cannot reject candidate after approval")
        candidate = _candidate_snapshot_from_agent_run(agent_run)
        repo = AgentCandidateReviewRepository(session)
        if existing is not None:
            review = repo.update_rejection(
                existing,
                candidate_payload=_json_dumps(candidate["candidate_payload"]),
                backtest_request_payload=_json_dumps(candidate["backtest_request_payload"]),
                operator=operator,
                operator_note=note,
                decided_at=now,
                updated_at=now,
            )
        else:
            review = repo.create_decision(
                source_agent_run_id=agent_run.id,
                status=STATUS_REJECTED,
                symbol=candidate["symbol"],
                strategy_name=candidate["strategy_name"],
                candidate_payload=_json_dumps(candidate["candidate_payload"]),
                backtest_request_payload=_json_dumps(candidate["backtest_request_payload"]),
                operator=operator,
                operator_note=note,
                decided_at=now,
                created_at=now,
            )
        session.expunge(review)
        return review
```

- [ ] **Step 5: Implement validation and refresh helpers used by approval**

Add these helpers to `candidate_reviews.py`:

```python
def _validated_candidate_from_agent_run(agent_run: AgentRunORM) -> dict[str, Any]:
    if agent_run.agent_type != AGENT_STRATEGY_IDEA:
        raise CandidateReviewValidationError("source agent run is not a strategy idea")
    if agent_run.status != "succeeded":
        raise CandidateReviewValidationError("source agent run has not succeeded")
    payload = _json_loads(agent_run.result_payload)
    if payload.get("parsed") is not True:
        raise CandidateReviewValidationError("strategy candidate was not parsed")
    if payload.get("validation_status") != "passed":
        raise CandidateReviewValidationError("candidate validation did not pass")
    candidate_payload = payload.get("candidate_payload")
    if not isinstance(candidate_payload, dict):
        raise CandidateReviewValidationError("missing candidate payload")
    backtest_request_payload = payload.get("backtest_request_payload")
    if not isinstance(backtest_request_payload, dict):
        raise CandidateReviewValidationError("missing backtest request payload")
    if backtest_request_payload.get("job_type") != BACKTEST_MA_CROSS:
        raise CandidateReviewValidationError("unsupported backtest job type")
    if not isinstance(backtest_request_payload.get("payload"), dict):
        raise CandidateReviewValidationError("missing backtest request payload")
    if payload.get("requires_human_approval") is not True:
        raise CandidateReviewValidationError("candidate does not require human approval")
    symbol = str(candidate_payload.get("symbol") or agent_run.symbol or "").strip()
    if not symbol:
        raise CandidateReviewValidationError("missing symbol")
    strategy_name = str(candidate_payload.get("strategy_name") or "").strip()
    if not strategy_name:
        raise CandidateReviewValidationError("missing strategy name")
    return {
        "symbol": symbol[:32],
        "strategy_name": strategy_name[:128],
        "candidate_payload": candidate_payload,
        "backtest_request_payload": backtest_request_payload,
    }


def _candidate_snapshot_from_agent_run(agent_run: AgentRunORM) -> dict[str, Any]:
    payload = _json_loads(agent_run.result_payload)
    candidate_payload = payload.get("candidate_payload")
    if not isinstance(candidate_payload, dict):
        candidate_payload = {}
    backtest_request_payload = payload.get("backtest_request_payload")
    if not isinstance(backtest_request_payload, dict):
        backtest_request_payload = {}
    symbol = str(candidate_payload.get("symbol") or agent_run.symbol or "").strip() or "unknown"
    strategy_name = str(candidate_payload.get("strategy_name") or "unknown").strip() or "unknown"
    return {
        "symbol": symbol[:32],
        "strategy_name": strategy_name[:128],
        "candidate_payload": candidate_payload,
        "backtest_request_payload": backtest_request_payload,
    }


def _refresh_backtest_status_from_job_row(session, review: AgentCandidateReviewORM) -> None:
    if review.backtest_job_run_id is None:
        return
    job = JobRunRepository(session).get(review.backtest_job_run_id)
    if job is None:
        return
    repo = AgentCandidateReviewRepository(session)
    if job.status == "succeeded":
        result_payload = _json_loads(job.result_payload)
        run_id = result_payload.get("run_id")
        if isinstance(run_id, int):
            repo.mark_backtest_succeeded(review, backtest_run_id=run_id, updated_at=_utcnow())
        return
    if job.status == "failed":
        repo.mark_backtest_failed(
            review,
            error_message=job.error_message or "backtest job failed",
            updated_at=_utcnow(),
        )


def _raise_existing_approval_conflict(existing: AgentCandidateReviewORM) -> None:
    if existing.status == STATUS_REJECTED:
        raise CandidateReviewConflictError("candidate already rejected")
    if existing.status in {
        STATUS_APPROVED,
        STATUS_BACKTEST_SUBMITTED,
        STATUS_BACKTEST_SUCCEEDED,
        STATUS_BACKTEST_FAILED,
        STATUS_REVIEW_REQUESTED,
        STATUS_REVIEW_SUCCEEDED,
        STATUS_REVIEW_FAILED,
    }:
        raise CandidateReviewConflictError("candidate already submitted")
    raise CandidateReviewConflictError(f"candidate is in unsupported state: {existing.status}")


def _clean_operator(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise CandidateReviewValidationError("operator is required")
    return cleaned[:OPERATOR_MAX_CHARS]


def _clean_note(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise CandidateReviewValidationError("note is required")
    return cleaned[:NOTE_MAX_CHARS]


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        return {"value": loaded}
    return loaded


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
```

- [ ] **Step 6: Run service tests**

Run:

```bash
pytest tests/integration/test_agent_candidate_approval_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Run task reviews**

Spec review:

```text
Task 2 implements narrow approve/reject inputs, exact stored backtest payload submission through submit_job_run(), duplicate approval conflicts, rejection terminal behavior, inline job result linking, and no paper/broker side effects.
```

Quality review:

```text
Service state transitions are explicit, invalid source states raise typed errors, note/operator values are bounded, DeepSeek keys are not read or persisted, and tests cover both success and failure paths.
```

- [ ] **Step 8: Commit**

Run:

```bash
git add src/quant_trading/agents/candidate_reviews.py tests/integration/test_agent_candidate_approval_service.py
git commit -m "feat: add candidate approval service"
```

---

### Task 3: Candidate Review HTTP APIs

**Files:**
- Create: `src/quant_trading/api/routes/agent_candidates.py`
- Modify: `src/quant_trading/api/main.py`
- Create: `tests/integration/test_agent_candidates_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/integration/test_agent_candidates_api.py`:

```python
import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import BrokerOrderEventORM, JobRunORM, PaperRunORM
from quant_trading.storage.repositories import AgentRunRepository


def _create_strategy_agent_run(engine):
    with session_scope(engine) as session:
        row = AgentRunRepository(session).create_running(
            agent_type="strategy_idea",
            symbol="000001",
            model_name="fake-llm",
            request_payload="{}",
            job_run_id=None,
            started_at=datetime(2026, 6, 24, 9, 0, 0),
        )
        AgentRunRepository(session).mark_succeeded(
            row,
            metrics_payload="{}",
            result_payload=json.dumps(
                {
                    "parsed": True,
                    "validation_status": "passed",
                    "candidate_payload": {
                        "strategy_name": "ma_cross",
                        "symbol": "000001",
                        "parameters": {
                            "short_window": 5,
                            "long_window": 20,
                            "order_size": 100,
                        },
                        "requires_human_approval": True,
                    },
                    "backtest_request_payload": {
                        "job_type": "backtest_ma_cross",
                        "payload": {
                            "symbol": "000001",
                            "short_window": 5,
                            "long_window": 20,
                            "order_size": 100,
                            "initial_cash": "100000",
                        },
                    },
                    "requires_human_approval": True,
                },
                sort_keys=True,
            ),
            finished_at=datetime(2026, 6, 24, 9, 0, 1),
            duration_ms=1,
        )
        return row.id


def test_candidate_approve_endpoint_submits_backtest_and_read_apis_return_decoded_payloads(
    legacy_sqlite_db: Path,
):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)
    agent_run_id = _create_strategy_agent_run(engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    approve_response = client.post(
        f"/agent-candidates/{agent_run_id}/approve",
        json={"operator": "local", "note": "approved for research backtest"},
    )
    list_response = client.get("/agent-candidates")
    get_response = client.get(f"/agent-candidates/{approve_response.json()['id']}")

    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["status"] == "backtest_succeeded"
    assert approved["source_agent_run_id"] == agent_run_id
    assert approved["candidate_payload"]["strategy_name"] == "ma_cross"
    assert approved["backtest_request_payload"]["job_type"] == "backtest_ma_cross"
    assert approved["backtest_job_run_id"] == 1
    assert approved["backtest_run_id"] == 1
    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [approved["id"]]
    assert get_response.status_code == 200
    assert get_response.json()["id"] == approved["id"]
    with session_scope(engine) as session:
        assert session.query(JobRunORM).count() == 1
        assert session.query(PaperRunORM).count() == 0
        assert session.query(BrokerOrderEventORM).count() == 0


def test_candidate_reject_endpoint_is_terminal_and_creates_no_job():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    agent_run_id = _create_strategy_agent_run(engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    reject_response = client.post(
        f"/agent-candidates/{agent_run_id}/reject",
        json={"operator": "local", "note": "insufficient thesis"},
    )
    approve_response = client.post(
        f"/agent-candidates/{agent_run_id}/approve",
        json={"operator": "local", "note": "changed mind"},
    )

    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert approve_response.status_code == 409
    assert approve_response.json()["detail"] == "candidate already rejected"
    with session_scope(engine) as session:
        assert session.query(JobRunORM).count() == 0


def test_candidate_api_maps_missing_and_validation_errors():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    missing = client.get("/agent-candidates/999")
    approve_missing = client.post(
        "/agent-candidates/999/approve",
        json={"operator": "local", "note": "approved"},
    )
    malformed = client.post(
        "/agent-candidates/1/approve",
        json={"operator": "", "note": ""},
    )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "candidate review not found"}
    assert approve_missing.status_code == 404
    assert approve_missing.json() == {"detail": "source agent run not found"}
    assert malformed.status_code == 400
```

- [ ] **Step 2: Run API tests to verify failure**

Run:

```bash
pytest tests/integration/test_agent_candidates_api.py -q
```

Expected: FAIL because `/agent-candidates` routes are not registered.

- [ ] **Step 3: Add router implementation**

Create `src/quant_trading/api/routes/agent_candidates.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from quant_trading.agents.candidate_reviews import (
    CandidateReviewConflictError,
    CandidateReviewNotFoundError,
    CandidateReviewValidationError,
    approve_strategy_candidate,
    candidate_review_payload,
    reject_strategy_candidate,
)
from quant_trading.jobs.queue import make_queue
from quant_trading.storage.db import session_scope
from quant_trading.storage.repositories import AgentCandidateReviewRepository

router = APIRouter(prefix="/agent-candidates", tags=["agent-candidates"])


class CandidateDecisionRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1, max_length=4000)


@router.get("")
def list_agent_candidates(
    request: Request,
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = AgentCandidateReviewRepository(session).list_recent(
            status=status,
            symbol=symbol,
            limit=limit,
        )
        return [candidate_review_payload(row) for row in rows]


@router.get("/{candidate_review_id}")
def get_agent_candidate(candidate_review_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = AgentCandidateReviewRepository(session).get(candidate_review_id)
        if row is None:
            raise HTTPException(status_code=404, detail="candidate review not found")
        return candidate_review_payload(row)


@router.post("/{agent_run_id}/approve")
def approve_agent_candidate(
    agent_run_id: int,
    payload: CandidateDecisionRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        row = approve_strategy_candidate(
            request.app.state.engine,
            source_agent_run_id=agent_run_id,
            operator=payload.operator,
            note=payload.note,
            settings=request.app.state.settings,
            queue_factory=make_queue,
        )
        return candidate_review_payload(row)
    except CandidateReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CandidateReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CandidateReviewValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{agent_run_id}/reject")
def reject_agent_candidate(
    agent_run_id: int,
    payload: CandidateDecisionRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        row = reject_strategy_candidate(
            request.app.state.engine,
            source_agent_run_id=agent_run_id,
            operator=payload.operator,
            note=payload.note,
        )
        return candidate_review_payload(row)
    except CandidateReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CandidateReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CandidateReviewValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 4: Register router**

In `src/quant_trading/api/main.py`, add `agent_candidates` to the route import tuple and include it before `agents.router`:

```python
from quant_trading.api.routes import (
    agent_candidates,
    agents,
    dashboard,
    backtests,
    data_sync,
    health,
    instruments,
    jobs,
    paper,
    schedules,
    workflows,
)
```

```python
    app.include_router(agent_candidates.router)
```

- [ ] **Step 5: Run API tests**

Run:

```bash
pytest tests/integration/test_agent_candidates_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Run task reviews**

Spec review:

```text
Task 3 exposes list/get/approve/reject APIs with the specified payload shape and maps 404, 409, and 400 errors without adding UI or paper/broker execution.
```

Quality review:

```text
Routes are thin, validation is delegated to the service, JSON payloads are decoded through the shared serializer, and auth middleware continues to cover routes through the existing FastAPI app.
```

- [ ] **Step 7: Commit**

Run:

```bash
git add src/quant_trading/api/routes/agent_candidates.py src/quant_trading/api/main.py tests/integration/test_agent_candidates_api.py
git commit -m "feat: expose candidate approval api"
```

---

### Task 4: Candidate Backtest Refresh

**Files:**
- Modify: `src/quant_trading/agents/candidate_reviews.py`
- Modify: `src/quant_trading/api/routes/agent_candidates.py`
- Modify: `tests/integration/test_agent_candidate_approval_service.py`
- Modify: `tests/integration/test_agent_candidates_api.py`

- [ ] **Step 1: Add failing refresh service tests**

Append to `tests/integration/test_agent_candidate_approval_service.py`:

```python
from quant_trading.agents.candidate_reviews import refresh_candidate_backtest_status
from quant_trading.jobs.runtime import job_payload_dumps
from quant_trading.storage.models import BacktestRunORM
from quant_trading.storage.repositories import JobRunRepository


def test_refresh_links_completed_queued_backtest_job_result():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    agent_run_id = _create_agent_run(engine)
    review = approve_strategy_candidate(
        engine,
        source_agent_run_id=agent_run_id,
        operator="local",
        note="approved for research backtest",
        settings=AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"),
        queue_factory=lambda redis_url: _FakeQueue(),
    )
    assert review.status == "backtest_submitted"

    with session_scope(engine) as session:
        session.add(
            BacktestRunORM(
                id=99,
                strategy_name="ma_cross",
                symbol="000001",
                initial_cash=100000,
                final_equity=101000,
                status="done",
            )
        )
        job = JobRunRepository(session).get(review.backtest_job_run_id)
        JobRunRepository(session).mark_succeeded(
            job,
            result_payload=job_payload_dumps({"run_id": 99, "symbol": "000001"}),
            workflow_run_id=None,
            finished_at=datetime(2026, 6, 24, 10, 0, 0),
            duration_ms=1,
        )

    refreshed = refresh_candidate_backtest_status(engine, review.id)

    assert refreshed.status == "backtest_succeeded"
    assert refreshed.backtest_run_id == 99


def test_refresh_incomplete_job_conflicts():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    agent_run_id = _create_agent_run(engine)
    review = approve_strategy_candidate(
        engine,
        source_agent_run_id=agent_run_id,
        operator="local",
        note="approved for research backtest",
        settings=AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"),
        queue_factory=lambda redis_url: _FakeQueue(),
    )

    with pytest.raises(CandidateReviewConflictError, match="linked backtest job has not completed"):
        refresh_candidate_backtest_status(engine, review.id)


class _FakeRQJob:
    id = "rq-test-1"


class _FakeQueue:
    def enqueue(self, func, database_url, job_run_id):
        return _FakeRQJob()
```

- [ ] **Step 2: Add failing refresh API test**

Append to `tests/integration/test_agent_candidates_api.py`:

```python
def test_candidate_refresh_endpoint_reports_incomplete_job(monkeypatch):
    class FakeRQJob:
        id = "rq-test-1"

    class FakeQueue:
        def enqueue(self, func, database_url, job_run_id):
            return FakeRQJob()

    from quant_trading.api.routes import agent_candidates as candidate_route

    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    agent_run_id = _create_strategy_agent_run(engine)
    client = TestClient(
        create_app(
            engine=engine,
            settings=AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"),
        )
    )
    monkeypatch.setattr(candidate_route, "make_queue", lambda redis_url: FakeQueue())
    approve_response = client.post(
        f"/agent-candidates/{agent_run_id}/approve",
        json={"operator": "local", "note": "approved for research backtest"},
    )

    refresh_response = client.post(
        f"/agent-candidates/{approve_response.json()['id']}/refresh-backtest"
    )

    assert refresh_response.status_code == 409
    assert refresh_response.json() == {"detail": "linked backtest job has not completed"}
```

- [ ] **Step 3: Run refresh tests to verify failure**

Run:

```bash
pytest tests/integration/test_agent_candidate_approval_service.py::test_refresh_links_completed_queued_backtest_job_result tests/integration/test_agent_candidate_approval_service.py::test_refresh_incomplete_job_conflicts tests/integration/test_agent_candidates_api.py::test_candidate_refresh_endpoint_reports_incomplete_job -q
```

Expected: FAIL because `refresh_candidate_backtest_status` and the route do not exist.

- [ ] **Step 4: Implement refresh service**

Add to `src/quant_trading/agents/candidate_reviews.py`:

```python
def refresh_candidate_backtest_status(
    engine: Engine,
    candidate_review_id: int,
) -> AgentCandidateReviewORM:
    with session_scope(engine) as session:
        repo = AgentCandidateReviewRepository(session)
        review = repo.get(candidate_review_id)
        if review is None:
            raise CandidateReviewNotFoundError("candidate review not found")
        if review.backtest_job_run_id is None:
            raise CandidateReviewConflictError("candidate has no linked backtest job")
        job = JobRunRepository(session).get(review.backtest_job_run_id)
        if job is None:
            raise CandidateReviewNotFoundError("linked backtest job not found")
        if job.status not in {"succeeded", "failed"}:
            raise CandidateReviewConflictError("linked backtest job has not completed")
        _refresh_backtest_status_from_job_row(session, review)
        session.expunge(review)
        return review
```

Strengthen `_refresh_backtest_status_from_job_row()` so succeeded jobs without an integer `run_id` become `backtest_failed`:

```python
    if job.status == "succeeded":
        result_payload = _json_loads(job.result_payload)
        run_id = result_payload.get("run_id")
        if isinstance(run_id, int):
            repo.mark_backtest_succeeded(review, backtest_run_id=run_id, updated_at=_utcnow())
            return
        repo.mark_backtest_failed(
            review,
            error_message="completed backtest job did not return run_id",
            updated_at=_utcnow(),
        )
        return
```

- [ ] **Step 5: Add refresh API route**

In `src/quant_trading/api/routes/agent_candidates.py`, import `refresh_candidate_backtest_status`, then add:

```python
@router.post("/{candidate_review_id}/refresh-backtest")
def refresh_agent_candidate_backtest(
    candidate_review_id: int,
    request: Request,
) -> dict[str, Any]:
    try:
        row = refresh_candidate_backtest_status(
            request.app.state.engine,
            candidate_review_id,
        )
        return candidate_review_payload(row)
    except CandidateReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CandidateReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

- [ ] **Step 6: Run refresh tests**

Run:

```bash
pytest tests/integration/test_agent_candidate_approval_service.py tests/integration/test_agent_candidates_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Run task reviews**

Spec review:

```text
Task 4 adds explicit queued-job refresh, links completed backtest results, reports incomplete jobs as conflicts, and avoids schedulers or automatic background sync.
```

Quality review:

```text
Refresh only reads the linked job result, keeps missing/incomplete states explicit, and uses the same decoded payload shape as approval.
```

- [ ] **Step 8: Commit**

Run:

```bash
git add src/quant_trading/agents/candidate_reviews.py src/quant_trading/api/routes/agent_candidates.py tests/integration/test_agent_candidate_approval_service.py tests/integration/test_agent_candidates_api.py
git commit -m "feat: refresh candidate backtest status"
```

---

### Task 5: Backtest Review Prompt, Parser, And Metrics

**Files:**
- Create: `src/quant_trading/agents/backtest_review.py`
- Create: `tests/unit/test_backtest_review_agent.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_backtest_review_agent.py`:

```python
import json

from quant_trading.agents.backtest_review import (
    build_backtest_review_prompt,
    parse_backtest_review_response,
)


def _context():
    return {
        "candidate_review_id": 3,
        "backtest_run_id": 9,
        "symbol": "000001",
        "strategy_name": "ma_cross",
        "candidate_payload": {
            "strategy_name": "ma_cross",
            "symbol": "000001",
            "parameters": {"short_window": 5, "long_window": 20, "order_size": 100},
        },
        "backtest_request_payload": {
            "job_type": "backtest_ma_cross",
            "payload": {
                "symbol": "000001",
                "short_window": 5,
                "long_window": 20,
                "order_size": 100,
                "initial_cash": "100000",
            },
        },
        "source_strategy_spec": {
            "thesis": "Moving-average crossover trend research.",
            "failure_modes": ["Whipsaw in range-bound markets."],
        },
        "metrics": {
            "initial_cash": "100000",
            "final_equity": "101000",
            "absolute_pnl": "1000",
            "return_pct": "1",
            "status": "done",
            "equity_point_count": 121,
            "max_drawdown": "0",
            "order_count": 1,
        },
    }


def test_backtest_review_prompt_contains_safety_constraints_and_context():
    prompt = build_backtest_review_prompt(_context(), max_chars=8000)

    assert "do not claim future profitability" in prompt
    assert "do not give live trading instructions" in prompt
    assert "do not approve paper trading" in prompt
    assert "do not call brokers or exchanges" in prompt
    assert "do not output executable code" in prompt
    assert '"candidate_review_id": 3' in prompt
    assert '"backtest_run_id": 9' in prompt
    assert "paper_trading_readiness" in prompt


def test_parse_backtest_review_response_accepts_json_and_forces_research_only():
    result = parse_backtest_review_response(
        json.dumps(
            {
                "summary": "Positive return, but evidence is narrow.",
                "risk_flags": ["single_symbol_only"],
                "overfit_warnings": ["no_out_of_sample_test"],
                "paper_trading_readiness": "ready_for_paper_research",
                "recommended_next_steps": ["run out-of-sample test"],
            }
        ),
        candidate_review_id=3,
        backtest_run_id=9,
    )

    assert result == {
        "review_status": "completed",
        "candidate_review_id": 3,
        "backtest_run_id": 9,
        "summary": "Positive return, but evidence is narrow.",
        "risk_flags": ["single_symbol_only"],
        "overfit_warnings": ["no_out_of_sample_test"],
        "paper_trading_readiness": "ready_for_paper_research",
        "recommended_next_steps": ["run out-of-sample test"],
        "research_only": True,
    }


def test_parse_backtest_review_response_invalid_readiness_needs_review():
    result = parse_backtest_review_response(
        json.dumps(
            {
                "summary": "Looks ready for live trading.",
                "risk_flags": [],
                "overfit_warnings": [],
                "paper_trading_readiness": "approved",
                "recommended_next_steps": [],
            }
        ),
        candidate_review_id=3,
        backtest_run_id=9,
    )

    assert result["review_status"] == "needs_review"
    assert result["paper_trading_readiness"] == "needs_review"
    assert "invalid paper_trading_readiness" in result["summary"]
    assert result["research_only"] is True


def test_parse_backtest_review_response_narrative_fallback_is_bounded():
    result = parse_backtest_review_response(
        "Narrative " * 2000,
        candidate_review_id=3,
        backtest_run_id=9,
    )

    assert result["review_status"] == "needs_review"
    assert result["candidate_review_id"] == 3
    assert result["backtest_run_id"] == 9
    assert result["paper_trading_readiness"] == "needs_review"
    assert len(result["summary"]) <= 12000
    assert result["research_only"] is True
```

- [ ] **Step 2: Run unit tests to verify failure**

Run:

```bash
pytest tests/unit/test_backtest_review_agent.py -q
```

Expected: FAIL because `quant_trading.agents.backtest_review` does not exist.

- [ ] **Step 3: Implement prompt and parser**

Create `src/quant_trading/agents/backtest_review.py`:

```python
from __future__ import annotations

from decimal import Decimal
import json
from typing import Any

from sqlalchemy import Engine, func, select

from quant_trading.agents.models import RESULT_VALUE_MAX_CHARS
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    AgentRunORM,
    BacktestEquityPointORM,
    BacktestOrderORM,
    BacktestRunORM,
)

READINESS_NOT_READY = "not_ready"
READINESS_NEEDS_REVIEW = "needs_review"
READINESS_READY_FOR_PAPER_RESEARCH = "ready_for_paper_research"
ALLOWED_READINESS = {
    READINESS_NOT_READY,
    READINESS_NEEDS_REVIEW,
    READINESS_READY_FOR_PAPER_RESEARCH,
}


def build_backtest_review_prompt(context: dict[str, Any], max_chars: int) -> str:
    prompt = f"""
You are a quantitative research reviewer.
Assess only the research quality and risks of this backtest result.
Do not claim future profitability.
Do not give live trading instructions.
Do not approve paper trading.
Do not call brokers or exchanges.
Do not output executable code.
Do not provide buy or sell instructions.

Return one JSON object with these keys:
summary, risk_flags, overfit_warnings, paper_trading_readiness, recommended_next_steps.

Allowed paper_trading_readiness values:
not_ready, needs_review, ready_for_paper_research.

Candidate and backtest context:
{json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)}
""".strip()
    return prompt[:max_chars]


def parse_backtest_review_response(
    content: str,
    *,
    candidate_review_id: int,
    backtest_run_id: int,
) -> dict[str, Any]:
    bounded = content.strip()[:RESULT_VALUE_MAX_CHARS]
    try:
        parsed = json.loads(bounded)
    except json.JSONDecodeError:
        return _fallback_result(candidate_review_id, backtest_run_id, bounded)
    if not isinstance(parsed, dict):
        return _fallback_result(candidate_review_id, backtest_run_id, bounded)

    readiness = str(parsed.get("paper_trading_readiness") or "").strip()
    if readiness not in ALLOWED_READINESS:
        return {
            "review_status": "needs_review",
            "candidate_review_id": candidate_review_id,
            "backtest_run_id": backtest_run_id,
            "summary": f"invalid paper_trading_readiness: {readiness}",
            "risk_flags": _string_list(parsed.get("risk_flags")),
            "overfit_warnings": _string_list(parsed.get("overfit_warnings")),
            "paper_trading_readiness": READINESS_NEEDS_REVIEW,
            "recommended_next_steps": _string_list(parsed.get("recommended_next_steps")),
            "research_only": True,
        }

    return {
        "review_status": "completed",
        "candidate_review_id": candidate_review_id,
        "backtest_run_id": backtest_run_id,
        "summary": str(parsed.get("summary") or "")[:4000],
        "risk_flags": _string_list(parsed.get("risk_flags")),
        "overfit_warnings": _string_list(parsed.get("overfit_warnings")),
        "paper_trading_readiness": readiness,
        "recommended_next_steps": _string_list(parsed.get("recommended_next_steps")),
        "research_only": True,
    }


def _fallback_result(
    candidate_review_id: int,
    backtest_run_id: int,
    narrative: str,
) -> dict[str, Any]:
    return {
        "review_status": "needs_review",
        "candidate_review_id": candidate_review_id,
        "backtest_run_id": backtest_run_id,
        "summary": narrative[:RESULT_VALUE_MAX_CHARS],
        "risk_flags": ["unstructured_review_output"],
        "overfit_warnings": [],
        "paper_trading_readiness": READINESS_NEEDS_REVIEW,
        "recommended_next_steps": ["rerun the review agent and inspect the raw narrative"],
        "research_only": True,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:512] for item in value if str(item).strip()]
```

- [ ] **Step 4: Add context loader and metrics**

Append to `backtest_review.py`:

```python
def load_backtest_review_context(
    engine: Engine,
    *,
    candidate_review_id: int,
    backtest_run_id: int | None = None,
) -> dict[str, Any]:
    with session_scope(engine) as session:
        review = session.get(AgentCandidateReviewORM, candidate_review_id)
        if review is None:
            raise ValueError("candidate review not found")
        resolved_backtest_run_id = backtest_run_id or review.backtest_run_id
        if resolved_backtest_run_id is None:
            raise ValueError("candidate review has no linked backtest run")
        backtest = session.get(BacktestRunORM, resolved_backtest_run_id)
        if backtest is None:
            raise ValueError("backtest run not found")
        source_agent = session.get(AgentRunORM, review.source_agent_run_id)
        source_result = _json_loads(source_agent.result_payload) if source_agent else {}
        metrics = _load_backtest_metrics(session, backtest)
        return {
            "candidate_review_id": review.id,
            "backtest_run_id": backtest.id,
            "symbol": backtest.symbol,
            "strategy_name": backtest.strategy_name,
            "candidate_payload": _json_loads(review.candidate_payload),
            "backtest_request_payload": _json_loads(review.backtest_request_payload),
            "source_strategy_spec": source_result.get("spec") if isinstance(source_result.get("spec"), dict) else {},
            "metrics": metrics,
        }


def _load_backtest_metrics(session, backtest: BacktestRunORM) -> dict[str, Any]:
    initial_cash = Decimal(str(backtest.initial_cash))
    final_equity = Decimal(str(backtest.final_equity))
    absolute_pnl = final_equity - initial_cash
    return_pct = Decimal("0") if initial_cash == 0 else (absolute_pnl / initial_cash) * Decimal("100")
    max_drawdown = session.scalar(
        select(func.max(BacktestEquityPointORM.drawdown)).where(
            BacktestEquityPointORM.run_id == backtest.id
        )
    )
    equity_point_count = session.scalar(
        select(func.count()).select_from(BacktestEquityPointORM).where(
            BacktestEquityPointORM.run_id == backtest.id
        )
    )
    order_count = session.scalar(
        select(func.count()).select_from(BacktestOrderORM).where(
            BacktestOrderORM.run_id == backtest.id
        )
    )
    return {
        "initial_cash": _plain_decimal(initial_cash),
        "final_equity": _plain_decimal(final_equity),
        "absolute_pnl": _plain_decimal(absolute_pnl),
        "return_pct": _plain_decimal(return_pct),
        "status": backtest.status,
        "symbol": backtest.symbol,
        "strategy_name": backtest.strategy_name,
        "equity_point_count": int(equity_point_count or 0),
        "max_drawdown": _plain_decimal(Decimal(str(max_drawdown or 0))),
        "order_count": int(order_count or 0),
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _plain_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
```

- [ ] **Step 5: Run unit tests**

Run:

```bash
pytest tests/unit/test_backtest_review_agent.py -q
```

Expected: PASS.

- [ ] **Step 6: Run task reviews**

Spec review:

```text
Task 5 adds prompt safety constraints, conservative metrics, required output fields, readiness allow-listing, and bounded narrative fallback without adding job dispatch or paper/broker behavior.
```

Quality review:

```text
The parser returns a stable JSON shape for valid and invalid LLM output, context loading reads only persisted artifacts, and numeric metrics are serialized as strings for JSON stability.
```

- [ ] **Step 7: Commit**

Run:

```bash
git add src/quant_trading/agents/backtest_review.py tests/unit/test_backtest_review_agent.py
git commit -m "feat: add backtest review prompt parser"
```

---

### Task 6: Backtest Review Agent, Job Runtime, And Job API

**Files:**
- Modify: `src/quant_trading/agents/models.py`
- Modify: `src/quant_trading/agents/service.py`
- Modify: `src/quant_trading/jobs/runtime.py`
- Modify: `src/quant_trading/api/routes/jobs.py`
- Modify: `tests/integration/test_agents_jobs.py`

- [ ] **Step 1: Add failing integration tests**

Append to `tests/integration/test_agents_jobs.py`:

```python
from quant_trading.agents.candidate_reviews import approve_strategy_candidate
from quant_trading.agents.models import BacktestReviewRequest
from quant_trading.agents.service import run_backtest_review_agent
from quant_trading.storage.models import AgentCandidateReviewORM


BACKTEST_REVIEW_RESPONSE = json.dumps(
    {
        "summary": "The backtest is useful but narrow and needs more validation.",
        "risk_flags": ["single_symbol_only"],
        "overfit_warnings": ["no_out_of_sample_test"],
        "paper_trading_readiness": "not_ready",
        "recommended_next_steps": [
            "run an out-of-sample backtest",
            "test parameter sensitivity",
        ],
    },
    ensure_ascii=False,
)


def _create_approved_candidate_with_backtest(engine, legacy_sqlite_db: Path):
    import_legacy_sqlite(legacy_sqlite_db, engine)
    result = run_strategy_idea_agent(
        engine,
        StrategyIdeaRequest(idea="Trend pullback strategy", symbol="000001"),
        llm_client=FakeLLMClient(VALID_MA_CROSS_RESPONSE),
    )
    return approve_strategy_candidate(
        engine,
        source_agent_run_id=result["agent_run_id"],
        operator="local",
        note="approved for research backtest",
        settings=AppSettings(job_executor="inline"),
    )


def test_run_backtest_review_agent_persists_research_only_result(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    review = _create_approved_candidate_with_backtest(engine, legacy_sqlite_db)

    result = run_backtest_review_agent(
        engine,
        BacktestReviewRequest(candidate_review_id=review.id),
        llm_client=FakeLLMClient(BACKTEST_REVIEW_RESPONSE),
        job_run_id=8,
    )

    assert result["agent_type"] == "backtest_review"
    assert result["candidate_review_id"] == review.id
    assert result["backtest_run_id"] == review.backtest_run_id
    assert result["paper_trading_readiness"] == "not_ready"
    assert result["research_only"] is True
    with session_scope(engine) as session:
        agent = session.get(AgentRunORM, result["agent_run_id"])
        refreshed = session.get(AgentCandidateReviewORM, review.id)
        assert agent is not None
        assert agent.status == "succeeded"
        assert agent.agent_type == "backtest_review"
        assert agent.job_run_id == 8
        assert refreshed.status == "review_succeeded"
        assert refreshed.review_agent_run_id == agent.id


def test_backtest_review_job_api_persists_agent_run_and_creates_no_trading_rows(
    monkeypatch,
    legacy_sqlite_db: Path,
):
    from quant_trading.jobs import runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient(BACKTEST_REVIEW_RESPONSE),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    review = _create_approved_candidate_with_backtest(engine, legacy_sqlite_db)
    with session_scope(engine) as session:
        backtest_count_before = session.query(BacktestRunORM).count()
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    response = client.post(
        "/jobs/agents/backtest-review",
        json={"candidate_review_id": review.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "agent_backtest_review"
    assert payload["status"] == "succeeded"
    assert payload["result_payload"]["agent_type"] == "backtest_review"
    assert payload["result_payload"]["paper_trading_readiness"] == "not_ready"
    with session_scope(engine) as session:
        assert session.query(BacktestRunORM).count() == backtest_count_before
        assert session.query(PaperRunORM).count() == 0
        assert session.query(BrokerOrderEventORM).count() == 0
        job_payloads = [
            row.request_payload + row.result_payload
            for row in session.query(JobRunORM).all()
        ]
        workflow_payloads = [
            row.request_payload + row.result_payload
            for row in session.query(WorkflowRunORM).all()
        ]
    assert "DEEPSEEK_API_KEY" not in "".join(job_payloads + workflow_payloads)
```

Add `WorkflowRunORM` to the model imports at the top of `tests/integration/test_agents_jobs.py`.

- [ ] **Step 2: Run selected tests to verify failure**

Run:

```bash
pytest tests/integration/test_agents_jobs.py::test_run_backtest_review_agent_persists_research_only_result tests/integration/test_agents_jobs.py::test_backtest_review_job_api_persists_agent_run_and_creates_no_trading_rows -q
```

Expected: FAIL because `BacktestReviewRequest`, `run_backtest_review_agent`, and `/jobs/agents/backtest-review` do not exist.

- [ ] **Step 3: Add model constant and request dataclass**

In `src/quant_trading/agents/models.py`, add:

```python
AGENT_BACKTEST_REVIEW = "backtest_review"
```

Add after `StrategyIdeaRequest`:

```python
@dataclass(frozen=True)
class BacktestReviewRequest:
    candidate_review_id: int
    backtest_run_id: int | None = None
```

- [ ] **Step 4: Add service function**

In `src/quant_trading/agents/service.py`, import:

```python
from quant_trading.agents.backtest_review import (
    build_backtest_review_prompt,
    load_backtest_review_context,
    parse_backtest_review_response,
)
from quant_trading.agents.candidate_reviews import STATUS_BACKTEST_SUCCEEDED
from quant_trading.agents.models import AGENT_BACKTEST_REVIEW, BacktestReviewRequest
from quant_trading.storage.repositories import AgentCandidateReviewRepository
```

Then add:

```python
def run_backtest_review_agent(
    engine: Engine,
    request: BacktestReviewRequest,
    *,
    llm_client: LLMClient | None = None,
    llm_client_factory: Callable[[AppSettings], LLMClient] | None = None,
    job_run_id: int | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    settings = settings or AppSettings()
    started_at = _utcnow()
    started_counter = time.perf_counter()
    request_payload = _json_dumps(
        {
            "candidate_review_id": request.candidate_review_id,
            "backtest_run_id": request.backtest_run_id,
        }
    )

    context = load_backtest_review_context(
        engine,
        candidate_review_id=request.candidate_review_id,
        backtest_run_id=request.backtest_run_id,
    )
    with session_scope(engine) as session:
        row = AgentRunRepository(session).create_running(
            agent_type=AGENT_BACKTEST_REVIEW,
            symbol=str(context.get("symbol") or "")[:32] or None,
            model_name=getattr(llm_client, "model", settings.deepseek_model),
            request_payload=request_payload,
            job_run_id=job_run_id,
            started_at=started_at,
        )
        agent_run_id = row.id
        review = AgentCandidateReviewRepository(session).get(request.candidate_review_id)
        if review is not None:
            if review.status != STATUS_BACKTEST_SUCCEEDED:
                raise ValueError("candidate review backtest has not succeeded")
            AgentCandidateReviewRepository(session).mark_review_requested(
                review,
                review_agent_run_id=agent_run_id,
                updated_at=started_at,
            )

    try:
        llm_client = llm_client or (llm_client_factory or DeepSeekLLMClient.from_settings)(settings)
        prompt = build_backtest_review_prompt(context, settings.agent_prompt_max_chars)
        response = llm_client.complete(prompt)
        parsed_review = parse_backtest_review_response(
            response.content[: settings.agent_result_max_chars],
            candidate_review_id=request.candidate_review_id,
            backtest_run_id=int(context["backtest_run_id"]),
        )
        result_payload = {
            "agent_run_id": agent_run_id,
            "agent_type": AGENT_BACKTEST_REVIEW,
            **parsed_review,
            "disclaimer": RESEARCH_DISCLAIMER,
        }
        finished_at = _utcnow()
        with session_scope(engine) as session:
            agent_row = AgentRunRepository(session).get(agent_run_id)
            if agent_row is not None:
                AgentRunRepository(session).mark_succeeded(
                    agent_row,
                    metrics_payload=_json_dumps(context["metrics"]),
                    result_payload=_json_dumps(result_payload),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
            review = AgentCandidateReviewRepository(session).get(request.candidate_review_id)
            if review is not None:
                AgentCandidateReviewRepository(session).mark_review_succeeded(
                    review,
                    review_agent_run_id=agent_run_id,
                    updated_at=finished_at,
                )
        return result_payload
    except Exception as exc:
        finished_at = _utcnow()
        with session_scope(engine) as session:
            agent_row = AgentRunRepository(session).get(agent_run_id)
            if agent_row is not None:
                AgentRunRepository(session).mark_failed(
                    agent_row,
                    _sanitize_error(exc),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
            review = AgentCandidateReviewRepository(session).get(request.candidate_review_id)
            if review is not None:
                AgentCandidateReviewRepository(session).mark_review_failed(
                    review,
                    error_message=_sanitize_error(exc),
                    updated_at=finished_at,
                )
        raise
```

- [ ] **Step 5: Add job runtime dispatch**

In `src/quant_trading/jobs/runtime.py`, import `BacktestReviewRequest` and `run_backtest_review_agent`, then add:

```python
JOB_AGENT_BACKTEST_REVIEW = "agent_backtest_review"
```

Add it to `SUPPORTED_JOB_TYPES`.

In `execute_job_run_with_engine()`, include it in the agent payload injection set:

```python
if job_type in {
    MARKET_DATA_SYNC,
    JOB_AGENT_MARKET_ANALYSIS,
    JOB_AGENT_STRATEGY_IDEA,
    JOB_AGENT_BACKTEST_REVIEW,
}:
    request_payload = {**request_payload, "job_run_id": job_run_id}
```

In the `settings=_settings_from_agent_payload(...)` condition, include `JOB_AGENT_BACKTEST_REVIEW`.

Add to `_execute_payload()`:

```python
    if job_type == JOB_AGENT_BACKTEST_REVIEW:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        settings = settings or _settings_from_agent_payload(payload)
        return run_backtest_review_agent(
            engine,
            BacktestReviewRequest(
                candidate_review_id=int(payload["candidate_review_id"]),
                backtest_run_id=int(payload["backtest_run_id"])
                if payload.get("backtest_run_id")
                else None,
            ),
            llm_client_factory=build_agent_llm_client,
            job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
            settings=settings,
        )
```

- [ ] **Step 6: Add job API**

In `src/quant_trading/api/routes/jobs.py`, import `JOB_AGENT_BACKTEST_REVIEW`, add request model:

```python
class AgentBacktestReviewRequest(BaseModel):
    candidate_review_id: int = Field(gt=0)
    backtest_run_id: int | None = Field(default=None, gt=0)
```

Add endpoint after `create_agent_strategy_idea_job()`:

```python
@router.post("/agents/backtest-review")
def create_agent_backtest_review_job(
    payload: AgentBacktestReviewRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            JOB_AGENT_BACKTEST_REVIEW,
            _agent_job_payload(payload.model_dump(mode="json"), request.app.state.settings),
            make_queue,
        )
    )
```

- [ ] **Step 7: Run integration tests**

Run:

```bash
pytest tests/integration/test_agents_jobs.py -q
```

Expected: PASS.

- [ ] **Step 8: Run task reviews**

Spec review:

```text
Task 6 adds AGENT_BACKTEST_REVIEW, BacktestReviewRequest, a persisted backtest_review agent run, the agent_backtest_review job type, and POST /jobs/agents/backtest-review. It does not create backtests, paper runs, broker events, or API-key payloads.
```

Quality review:

```text
Runtime dispatch follows existing agent job patterns, failure marks both agent and candidate review records, and tests prove job execution is research-only.
```

- [ ] **Step 9: Commit**

Run:

```bash
git add src/quant_trading/agents/models.py src/quant_trading/agents/service.py src/quant_trading/jobs/runtime.py src/quant_trading/api/routes/jobs.py tests/integration/test_agents_jobs.py
git commit -m "feat: run backtest review agent jobs"
```

---

### Task 7: README Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Locate Quant Agent README section**

Run:

```bash
rg -n "Quant Agent|strategy-idea|agent-candidates|backtest-review" README.md
```

Expected: output shows the current Quant Agent section and existing v1/v2 examples.

- [ ] **Step 2: Update README with v3 workflow**

Add a v3 subsection under the existing Quant Agent documentation:

````markdown
### Quant Agent v3: approval and backtest review loop

`strategy_idea` still only produces a research candidate. V3 adds an operator approval record before any backtest job is submitted:

```text
strategy_idea agent run
  -> operator approve/reject
  -> backtest_ma_cross job
  -> refresh/link backtest result
  -> backtest_review agent job
  -> research-only readiness recommendation
```

Approve a validated candidate:

```bash
curl -X POST http://127.0.0.1:8000/agent-candidates/1/approve \
  -H "Content-Type: application/json" \
  -d '{"operator":"local","note":"approved for research backtest"}'
```

Reject a candidate:

```bash
curl -X POST http://127.0.0.1:8000/agent-candidates/1/reject \
  -H "Content-Type: application/json" \
  -d '{"operator":"local","note":"insufficient thesis"}'
```

List candidate review records:

```bash
curl http://127.0.0.1:8000/agent-candidates
```

Refresh a queued backtest result after the linked job completes:

```bash
curl -X POST http://127.0.0.1:8000/agent-candidates/1/refresh-backtest
```

Request a backtest review agent job:

```bash
curl -X POST http://127.0.0.1:8000/jobs/agents/backtest-review \
  -H "Content-Type: application/json" \
  -d '{"candidate_review_id":1}'
```

Approval means "submit this exact candidate payload to the deterministic research backtest job." It does not approve paper trading, create paper runs, call broker adapters, place orders, or permit generated strategy code. `backtest_review` output is a research-only readiness recommendation; it is not live-trading advice and is not permission to trade real capital.
````

- [ ] **Step 3: Run README smoke check**

Run:

```bash
rg -n "agent-candidates|backtest-review|paper runs|broker adapters" README.md
```

Expected: output includes the new v3 endpoint examples and safety text.

- [ ] **Step 4: Run task reviews**

Spec review:

```text
Task 7 documents approval, rejection, refresh, backtest-review job submission, research-only scope, no paper trading approval, and no broker orders.
```

Quality review:

```text
Examples use the exact API paths and narrow request bodies, and the safety language matches runtime behavior.
```

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md
git commit -m "docs: document quant agent approval loop"
```

---

### Task 8: Final Verification And Safety Audit

**Files:**
- No new files.
- Verify all files changed by Tasks 1-7.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
pytest tests/unit/test_backtest_review_agent.py tests/integration/test_agent_candidate_reviews_repository.py tests/integration/test_agent_candidate_approval_service.py tests/integration/test_agent_candidates_api.py tests/integration/test_agents_jobs.py tests/integration/test_migrations.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader regression tests**

Run:

```bash
pytest tests/unit tests/integration -q
```

Expected: PASS.

- [ ] **Step 3: Compile package**

Run:

```bash
python -m compileall -q src
```

Expected: command exits with status 0.

- [ ] **Step 4: Inspect git diff for safety invariants**

Run:

```bash
git diff -- src tests migrations README.md
```

Check these exact invariants:

```text
No generated strategy code execution was added.
No paper run is created from candidate approval or backtest review.
No broker adapter or broker order event is created from candidate approval or backtest review.
Approval submits only backtest_ma_cross jobs from stored candidate payloads.
Re-approval conflicts instead of submitting a second job.
Backtest review output is research-only and bounded.
DeepSeek API keys are not stored in job, workflow, agent, or candidate payloads.
```

- [ ] **Step 5: Run required final reviews**

Spec review:

```text
Every v3 spec requirement is implemented: candidate review table, approve/reject APIs, explicit backtest job submission, queued refresh, backtest_review agent/job/API, research-only output, error mappings, and documentation. Non-goals remain absent.
```

Quality review:

```text
The implementation follows existing repository, job runtime, FastAPI, Alembic, and test patterns. State transitions are explicit, error messages are clear, and the focused plus full test suites pass.
```

- [ ] **Step 6: Commit any final fixes**

If Step 1-5 changed files, commit them:

```bash
git add src tests migrations README.md
git commit -m "fix: polish quant agent approval loop"
```

If there are no changes, skip this commit.

- [ ] **Step 7: Prepare branch for push**

Run:

```bash
git status --short --branch
git log --oneline -8
```

Expected:

```text
## codex/quant-agent-v3-approval-review-loop
```

with a clean worktree and recent v3 commits.

## Execution Handoff

After this plan is saved and committed, continue with one of these:

1. **Subagent-Driven (recommended)** - dispatch a fresh worker per task and review between tasks.
2. **Inline Execution** - execute tasks in this session using `superpowers:executing-plans`, with review checkpoints after each task.
