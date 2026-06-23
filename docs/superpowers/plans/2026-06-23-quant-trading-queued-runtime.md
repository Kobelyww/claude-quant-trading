# Quant Trading Queued Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable `job_runs` execution layer so imports, MA Cross backtests, and paper ticks can run through observable inline or RQ-backed jobs.

**Architecture:** Keep `workflow_runs` as the command audit trail and add `job_runs` as the job lifecycle source of truth. API routes create job rows and dispatch through a small job service; inline mode executes immediately for tests/local development, while RQ mode enqueues `execute_job_run(database_url, job_run_id)` for worker execution.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Alembic, Pydantic Settings, Redis/RQ, pytest/TestClient.

---

## Baseline

Implementation worktree:

```bash
cd /private/tmp/quant-stage4-runtime
git status --short --branch
```

Expected: clean worktree on `codex/quant-stage4-runtime-tmp`.

Do not edit the root `LLM-Study` repository for Stage 5. Stage 5 spec and plan live inside the quant repo under `docs/superpowers/`.

## File Structure

Create:

- `src/quant_trading/jobs/runtime.py`
  Job type constants, job execution dispatch, inline execution, and RQ worker entrypoint.
- `src/quant_trading/jobs/service.py`
  Job submission service that creates `job_runs`, chooses inline or RQ executor, and stores RQ ids.
- `src/quant_trading/api/routes/jobs.py`
  API routes for creating, listing, and reading job runs.
- `tests/integration/test_job_runs_repository.py`
  Repository lifecycle tests.
- `tests/integration/test_job_runtime.py`
  Inline executor and worker entrypoint tests.
- `tests/integration/test_jobs_api.py`
  Job API and RQ enqueue behavior tests.
- `migrations/versions/20260623_0002_add_job_runs.py`
  Alembic migration for `job_runs`.

Modify:

- `src/quant_trading/config.py`
  Add `QUANT_JOB_EXECUTOR` and `REDIS_URL`.
- `tests/unit/test_settings.py`
  Cover job executor defaults and validation.
- `src/quant_trading/storage/models.py`
  Add `JobRunORM`.
- `src/quant_trading/storage/repositories.py`
  Add `JobRunRepository`.
- `src/quant_trading/workflows/runner.py`
  Add `run_with_audit()` that returns the workflow result and workflow run id while preserving existing `run()` behavior.
- `src/quant_trading/api/main.py`
  Include jobs router.
- `src/quant_trading/api/routes/dashboard.py`
  Render recent job runs.
- `tests/integration/test_migrations.py`
  Assert Alembic creates `job_runs`.
- `tests/integration/test_dashboard.py`
  Assert dashboard displays job runs.
- `docker-compose.yml`
  Set `QUANT_JOB_EXECUTOR=rq` for API and worker.
- `README.md`
  Document queued runtime, job APIs, executor modes, and safety boundary.

## Task 1: Job Settings, Model, Repository, And Migration

**Files:**

- Modify: `src/quant_trading/config.py`
- Modify: `src/quant_trading/storage/models.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `migrations/versions/20260623_0002_add_job_runs.py`
- Modify: `tests/unit/test_settings.py`
- Create: `tests/integration/test_job_runs_repository.py`
- Modify: `tests/integration/test_migrations.py`

- [ ] **Step 1: Add failing settings tests**

Append to `tests/unit/test_settings.py`:

```python
def test_settings_default_to_inline_job_executor(monkeypatch):
    monkeypatch.delenv("QUANT_JOB_EXECUTOR", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    settings = AppSettings()

    assert settings.job_executor == "inline"
    assert settings.redis_url == "redis://localhost:6379/0"


def test_settings_accept_rq_job_executor():
    settings = AppSettings(job_executor="RQ", redis_url="redis://redis:6379/0")

    assert settings.job_executor == "rq"
    assert settings.redis_url == "redis://redis:6379/0"


def test_settings_reject_unknown_job_executor():
    with pytest.raises(ValidationError) as exc_info:
        AppSettings(job_executor="celery")

    assert "QUANT_JOB_EXECUTOR must be inline or rq" in str(exc_info.value)
```

- [ ] **Step 2: Verify settings tests fail**

Run:

```bash
python -m pytest tests/unit/test_settings.py -q
```

Expected: FAIL because `AppSettings` has no `job_executor` or `redis_url`.

- [ ] **Step 3: Implement job runtime settings**

Modify `src/quant_trading/config.py`.

Add fields to `AppSettings`:

```python
    job_executor: str = Field(default="inline", validation_alias="QUANT_JOB_EXECUTOR")
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
```

Add this validator before `require_api_token_for_auth()`:

```python
    @field_validator("job_executor", mode="before")
    @classmethod
    def normalize_job_executor(cls, value: object) -> str:
        executor = str(value or "inline").strip().lower()
        if executor not in {"inline", "rq"}:
            raise ValueError("QUANT_JOB_EXECUTOR must be inline or rq")
        return executor
```

Inside `require_api_token_for_auth()`, add:

```python
        self.redis_url = self.redis_url.strip() or "redis://localhost:6379/0"
```

- [ ] **Step 4: Verify settings tests pass**

Run:

```bash
python -m pytest tests/unit/test_settings.py -q
```

Expected: PASS.

- [ ] **Step 5: Add failing repository lifecycle tests**

Create `tests/integration/test_job_runs_repository.py`:

```python
import json
from datetime import UTC, datetime

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobRunORM
from quant_trading.storage.repositories import JobRunRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_job_run_repository_lifecycle_records_status_and_payloads():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)

    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        row = repo.create_queued(
            job_type="backtest_ma_cross",
            request_payload='{"symbol": "000001"}',
            queued_at=now,
        )
        repo.mark_running(row, started_at=now)
        repo.mark_succeeded(
            row,
            result_payload='{"run_id": 7}',
            workflow_run_id=3,
            finished_at=now,
            duration_ms=25,
        )

    with session_scope(engine) as session:
        row = session.get(JobRunORM, 1)
        assert row is not None
        assert row.job_type == "backtest_ma_cross"
        assert row.status == "succeeded"
        assert row.progress == 100
        assert json.loads(row.request_payload) == {"symbol": "000001"}
        assert json.loads(row.result_payload) == {"run_id": 7}
        assert row.workflow_run_id == 3
        assert row.duration_ms == 25
        assert row.started_at is not None
        assert row.finished_at is not None


def test_job_run_repository_filters_recent_rows():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)

    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        first = repo.create_queued("import_legacy", "{}", now)
        second = repo.create_queued("paper_run_tick", "{}", now)
        repo.mark_failed(first, "bad input", now, 10)
        repo.mark_enqueued(second, rq_job_id="rq-123", updated_at=now)

    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        failed = repo.list_recent(status="failed")
        tick = repo.list_recent(job_type="paper_run_tick")

        assert [row.job_type for row in failed] == ["import_legacy"]
        assert [row.rq_job_id for row in tick] == ["rq-123"]
        assert repo.get(2).job_type == "paper_run_tick"
```

- [ ] **Step 6: Verify repository tests fail**

Run:

```bash
python -m pytest tests/integration/test_job_runs_repository.py -q
```

Expected: FAIL because `JobRunORM` and `JobRunRepository` do not exist.

- [ ] **Step 7: Add `JobRunORM`**

Modify `src/quant_trading/storage/models.py`.

Add after `WorkflowRunORM`:

```python
class JobRunORM(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    request_payload: Mapped[str] = mapped_column(Text, default="{}")
    result_payload: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_runs.id"),
        nullable=True,
        index=True,
    )
    rq_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 8: Add `JobRunRepository`**

Modify `src/quant_trading/storage/repositories.py`.

Update imports:

```python
from quant_trading.storage.models import InstrumentORM, JobRunORM, MarketBarORM, WorkflowRunORM
```

Append:

```python
class JobRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_queued(
        self,
        job_type: str,
        request_payload: str,
        queued_at: datetime,
    ) -> JobRunORM:
        row = JobRunORM(
            job_type=job_type,
            status="queued",
            progress=0,
            request_payload=request_payload,
            result_payload="{}",
            queued_at=queued_at,
            created_at=queued_at,
            updated_at=queued_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_enqueued(
        self,
        row: JobRunORM,
        rq_job_id: str,
        updated_at: datetime,
    ) -> JobRunORM:
        row.rq_job_id = rq_job_id
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_running(self, row: JobRunORM, started_at: datetime) -> JobRunORM:
        row.status = "running"
        row.progress = 10
        row.started_at = started_at
        row.updated_at = started_at
        self.session.flush()
        return row

    def mark_succeeded(
        self,
        row: JobRunORM,
        result_payload: str,
        workflow_run_id: int | None,
        finished_at: datetime,
        duration_ms: int,
    ) -> JobRunORM:
        row.status = "succeeded"
        row.progress = 100
        row.result_payload = result_payload
        row.error_message = None
        row.workflow_run_id = workflow_run_id
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        row.updated_at = finished_at
        self.session.flush()
        return row

    def mark_failed(
        self,
        row: JobRunORM,
        error_message: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> JobRunORM:
        row.status = "failed"
        row.error_message = error_message
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        row.updated_at = finished_at
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[JobRunORM]:
        statement = select(JobRunORM).order_by(JobRunORM.id.desc()).limit(limit)
        if status:
            statement = statement.where(JobRunORM.status == status)
        if job_type:
            statement = statement.where(JobRunORM.job_type == job_type)
        return list(self.session.scalars(statement).all())

    def get(self, job_run_id: int) -> JobRunORM | None:
        return self.session.get(JobRunORM, job_run_id)
```

- [ ] **Step 9: Verify repository tests pass**

Run:

```bash
python -m pytest tests/integration/test_job_runs_repository.py -q
```

Expected: PASS.

- [ ] **Step 10: Add migration test assertion**

Modify `tests/integration/test_migrations.py`:

```python
    assert "job_runs" in tables
```

Add it near the existing `"workflow_runs"` assertion.

- [ ] **Step 11: Verify migration test fails**

Run:

```bash
python -m pytest tests/integration/test_migrations.py -q
```

Expected: FAIL because Alembic does not create `job_runs`.

- [ ] **Step 12: Add Alembic revision**

Create `migrations/versions/20260623_0002_add_job_runs.py`:

```python
"""add job runs

Revision ID: 20260623_0002
Revises: 20260622_0001
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0002"
down_revision = "20260622_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("workflow_run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id"), nullable=True),
        sa.Column("rq_job_id", sa.String(length=128), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_job_runs_job_type", "job_runs", ["job_type"])
    op.create_index("ix_job_runs_status", "job_runs", ["status"])
    op.create_index("ix_job_runs_workflow_run_id", "job_runs", ["workflow_run_id"])
    op.create_index("ix_job_runs_rq_job_id", "job_runs", ["rq_job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_rq_job_id", table_name="job_runs")
    op.drop_index("ix_job_runs_workflow_run_id", table_name="job_runs")
    op.drop_index("ix_job_runs_status", table_name="job_runs")
    op.drop_index("ix_job_runs_job_type", table_name="job_runs")
    op.drop_table("job_runs")
```

- [ ] **Step 13: Verify Task 1**

Run:

```bash
python -m pytest tests/unit/test_settings.py tests/integration/test_job_runs_repository.py tests/integration/test_migrations.py -q
python -m py_compile src/quant_trading/config.py src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260623_0002_add_job_runs.py
```

Expected: all commands exit 0.

- [ ] **Step 14: Spec review for Task 1**

Check:

```bash
rg -n "JobRunORM|JobRunRepository|QUANT_JOB_EXECUTOR|REDIS_URL|job_runs" src tests migrations docs/superpowers/specs/2026-06-23-quant-trading-queued-runtime-design.md
```

Required evidence:

- `job_runs` fields match the spec.
- `QUANT_JOB_EXECUTOR` accepts only `inline` and `rq`.
- Migration creates `job_runs`.
- Repository supports queued, enqueued, running, succeeded, failed, list, and get.

- [ ] **Step 15: Quality review for Task 1**

Inspect:

- No API token appears in job payload defaults.
- `JobRunRepository` does not commit transactions itself.
- Existing workflow run repository remains backward compatible.

- [ ] **Step 16: Commit Task 1**

Run:

```bash
git add src/quant_trading/config.py src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260623_0002_add_job_runs.py tests/unit/test_settings.py tests/integration/test_job_runs_repository.py tests/integration/test_migrations.py
git commit -m "feat: add job run storage"
```

## Task 2: Workflow Audit Result And Job Runtime

**Files:**

- Modify: `src/quant_trading/workflows/runner.py`
- Create: `src/quant_trading/jobs/runtime.py`
- Create: `tests/integration/test_job_runtime.py`
- Modify: `tests/integration/test_workflow_runner.py`

- [ ] **Step 1: Add failing workflow audit result test**

Append to `tests/integration/test_workflow_runner.py`:

```python
def test_runner_can_return_workflow_run_id_with_result():
    engine = make_engine_with_schema()

    execution = WorkflowCommandRunner(engine).run_with_audit(
        "paper_create_account",
        {"name": "Audit Paper"},
        lambda: {"account_id": 9},
    )

    assert execution.result == {"account_id": 9}
    assert execution.workflow_run_id == 1
```

- [ ] **Step 2: Verify workflow audit result test fails**

Run:

```bash
python -m pytest tests/integration/test_workflow_runner.py::test_runner_can_return_workflow_run_id_with_result -q
```

Expected: FAIL because `run_with_audit()` does not exist.

- [ ] **Step 3: Implement `WorkflowCommandExecution` and `run_with_audit()`**

Modify `src/quant_trading/workflows/runner.py`.

Add imports:

```python
from dataclasses import dataclass
from typing import Generic
```

Add after `T = TypeVar("T")`:

```python
@dataclass(frozen=True)
class WorkflowCommandExecution(Generic[T]):
    result: T
    workflow_run_id: int
```

Change `WorkflowCommandRunner.run()` to:

```python
    def run(
        self,
        command_name: str,
        request_payload: dict[str, Any],
        callback: Callable[[], T],
    ) -> T:
        return self.run_with_audit(command_name, request_payload, callback).result
```

Move the existing body of `run()` into a new method:

```python
    def run_with_audit(
        self,
        command_name: str,
        request_payload: dict[str, Any],
        callback: Callable[[], T],
    ) -> WorkflowCommandExecution[T]:
```

In the success path, replace the final `return result` with:

```python
        return WorkflowCommandExecution(result=result, workflow_run_id=workflow_run_id)
```

Do not change failure behavior; exceptions must still mark the workflow run failed and then re-raise.

- [ ] **Step 4: Verify workflow runner tests pass**

Run:

```bash
python -m pytest tests/integration/test_workflow_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Add failing job runtime tests**

Create `tests/integration/test_job_runtime.py`:

```python
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from quant_trading.jobs.runtime import (
    BACKTEST_MA_CROSS,
    IMPORT_LEGACY,
    PAPER_RUN_TICK,
    execute_job_run_with_engine,
    job_payload_dumps,
    utcnow,
)
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobRunORM, WorkflowRunORM
from quant_trading.storage.repositories import JobRunRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def create_job(engine, job_type: str, payload: dict) -> int:
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(
            job_type=job_type,
            request_payload=job_payload_dumps(payload),
            queued_at=utcnow(),
        )
        return row.id


def get_job(engine, job_run_id: int) -> JobRunORM:
    with session_scope(engine) as session:
        return session.get(JobRunORM, job_run_id)


def test_execute_import_job_records_success_and_workflow_run(legacy_sqlite_db: Path):
    engine = make_engine_with_schema()
    job_run_id = create_job(engine, IMPORT_LEGACY, {"legacy_db_path": str(legacy_sqlite_db)})

    result = execute_job_run_with_engine(engine, job_run_id)

    job = get_job(engine, job_run_id)
    assert result["job_run_id"] == job_run_id
    assert job.status == "succeeded"
    assert job.progress == 100
    assert job.workflow_run_id == 1
    assert json.loads(job.result_payload) == {"imported_symbols": 1, "imported_bars": 121}
    with session_scope(engine) as session:
        workflow = session.scalar(select(WorkflowRunORM))
        assert workflow.command_name == IMPORT_LEGACY
        assert workflow.status == "succeeded"


def test_execute_backtest_job_failure_marks_job_failed(legacy_sqlite_db: Path):
    engine = make_engine_with_schema()
    import_job_id = create_job(engine, IMPORT_LEGACY, {"legacy_db_path": str(legacy_sqlite_db)})
    execute_job_run_with_engine(engine, import_job_id)
    job_run_id = create_job(
        engine,
        BACKTEST_MA_CROSS,
        {
            "symbol": "NO_SUCH",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
            "initial_cash": "100000",
        },
    )

    result = execute_job_run_with_engine(engine, job_run_id)

    job = get_job(engine, job_run_id)
    assert result["status"] == "failed"
    assert job.status == "failed"
    assert "no market bars found" in job.error_message
    assert json.loads(job.result_payload) == {}


def test_execute_unknown_job_id_raises_value_error():
    engine = make_engine_with_schema()

    with pytest.raises(ValueError, match="job run not found: 99"):
        execute_job_run_with_engine(engine, 99)


def test_execute_unsupported_job_type_marks_failed():
    engine = make_engine_with_schema()
    job_run_id = create_job(engine, "not_supported", {})

    result = execute_job_run_with_engine(engine, job_run_id)

    job = get_job(engine, job_run_id)
    assert result["status"] == "failed"
    assert job.status == "failed"
    assert "unsupported job type" in job.error_message
```

- [ ] **Step 6: Verify job runtime tests fail**

Run:

```bash
python -m pytest tests/integration/test_job_runtime.py -q
```

Expected: FAIL because `quant_trading.jobs.runtime` does not exist.

- [ ] **Step 7: Implement job runtime**

Create `src/quant_trading/jobs/runtime.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
import time
from typing import Any

from sqlalchemy import Engine

from quant_trading.storage.db import make_engine, session_scope
from quant_trading.storage.repositories import JobRunRepository
from quant_trading.workflows.operations import import_legacy_data, run_ma_cross_backtest, run_paper_tick
from quant_trading.workflows.runner import WorkflowCommandRunner, workflow_payload_dumps

IMPORT_LEGACY = "import_legacy"
BACKTEST_MA_CROSS = "backtest_ma_cross"
PAPER_RUN_TICK = "paper_run_tick"
SUPPORTED_JOB_TYPES = {IMPORT_LEGACY, BACKTEST_MA_CROSS, PAPER_RUN_TICK}


def execute_job_run(database_url: str, job_run_id: int) -> dict[str, Any]:
    engine = make_engine(database_url)
    return execute_job_run_with_engine(engine, job_run_id)


def execute_job_run_with_engine(engine: Engine, job_run_id: int) -> dict[str, Any]:
    started_at = utcnow()
    started_counter = time.perf_counter()
    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        job = repo.get(job_run_id)
        if job is None:
            raise ValueError(f"job run not found: {job_run_id}")
        repo.mark_running(job, started_at=started_at)
        job_type = job.job_type
        request_payload = _json_loads(job.request_payload)

    try:
        if job_type not in SUPPORTED_JOB_TYPES:
            raise ValueError(f"unsupported job type: {job_type}")
        execution = WorkflowCommandRunner(engine).run_with_audit(
            job_type,
            request_payload,
            lambda: _execute_payload(engine, job_type, request_payload),
        )
    except Exception as exc:
        finished_at = utcnow()
        duration_ms = _duration_ms(started_counter)
        error_message = _sanitize_error(exc)
        with session_scope(engine) as session:
            repo = JobRunRepository(session)
            job = repo.get(job_run_id)
            if job is not None:
                repo.mark_failed(job, error_message, finished_at, duration_ms)
        return {"job_run_id": job_run_id, "status": "failed", "error_message": error_message}

    finished_at = utcnow()
    duration_ms = _duration_ms(started_counter)
    result_payload = execution.result if isinstance(execution.result, dict) else {"result": execution.result}
    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        job = repo.get(job_run_id)
        if job is not None:
            repo.mark_succeeded(
                job,
                result_payload=job_payload_dumps(result_payload),
                workflow_run_id=execution.workflow_run_id,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
    return {"job_run_id": job_run_id, "status": "succeeded", "result": result_payload}


def job_payload_dumps(payload: dict[str, Any]) -> str:
    return workflow_payload_dumps(payload)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _execute_payload(engine: Engine, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if job_type == IMPORT_LEGACY:
        return import_legacy_data(engine, str(payload["legacy_db_path"]))
    if job_type == BACKTEST_MA_CROSS:
        return run_ma_cross_backtest(
            engine,
            symbol=str(payload["symbol"]),
            short_window=int(payload["short_window"]),
            long_window=int(payload["long_window"]),
            order_size=int(payload["order_size"]),
            initial_cash=Decimal(str(payload["initial_cash"])),
        )
    if job_type == PAPER_RUN_TICK:
        return run_paper_tick(engine, int(payload["run_id"]))
    raise ValueError(f"unsupported job type: {job_type}")


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("job payload must be an object")
    return loaded


def _duration_ms(started_counter: float) -> int:
    return max(0, int((time.perf_counter() - started_counter) * 1000))


def _sanitize_error(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__)[:1000]
```

- [ ] **Step 8: Verify job runtime tests pass**

Run:

```bash
python -m pytest tests/integration/test_workflow_runner.py tests/integration/test_job_runtime.py -q
```

Expected: PASS.

- [ ] **Step 9: Spec review for Task 2**

Check:

```bash
rg -n "run_with_audit|WorkflowCommandExecution|execute_job_run|execute_job_run_with_engine|SUPPORTED_JOB_TYPES|workflow_run_id" src tests docs/superpowers/specs/2026-06-23-quant-trading-queued-runtime-design.md
```

Required evidence:

- Job runtime supports `import_legacy`, `backtest_ma_cross`, and `paper_run_tick`.
- Job runtime delegates to workflow operations through `WorkflowCommandRunner.run_with_audit()`.
- Failed jobs are persisted as failed and do not raise for workflow business failures.
- Missing job id still raises because no row can be updated.

- [ ] **Step 10: Quality review for Task 2**

Inspect:

- Worker runtime has no direct strategy business logic except payload dispatch.
- Job payload JSON serialization reuses workflow JSON-safe serialization.
- `WorkflowCommandRunner.run()` remains backward compatible for existing routes.

- [ ] **Step 11: Commit Task 2**

Run:

```bash
git add src/quant_trading/workflows/runner.py src/quant_trading/jobs/runtime.py tests/integration/test_workflow_runner.py tests/integration/test_job_runtime.py
git commit -m "feat: execute audited job runs"
```

## Task 3: Job Submission Service And API Routes

**Files:**

- Create: `src/quant_trading/jobs/service.py`
- Create: `src/quant_trading/api/routes/jobs.py`
- Modify: `src/quant_trading/api/main.py`
- Create: `tests/integration/test_jobs_api.py`
- Modify: `tests/integration/test_runtime_auth.py`

- [ ] **Step 1: Add failing API tests**

Create `tests/integration/test_jobs_api.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobRunORM


def make_client(settings: AppSettings | None = None):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    settings = settings or AppSettings(job_executor="inline")
    return TestClient(create_app(engine=engine, settings=settings)), engine


def test_inline_import_job_api_returns_succeeded_job(legacy_sqlite_db: Path):
    client, engine = make_client()

    response = client.post("/jobs/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "import_legacy"
    assert payload["status"] == "succeeded"
    assert payload["progress"] == 100
    assert payload["workflow_run_id"] == 1
    with session_scope(engine) as session:
        assert session.scalar(select(JobRunORM.status)) == "succeeded"


def test_job_read_apis_filter_and_get_jobs(legacy_sqlite_db: Path):
    client, _ = make_client()
    created = client.post("/jobs/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)}).json()

    list_response = client.get("/jobs", params={"status": "succeeded", "job_type": "import_legacy"})
    get_response = client.get(f"/jobs/{created['id']}")
    missing_response = client.get("/jobs/999")

    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [created["id"]]
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "job run not found"}


def test_rq_executor_enqueues_without_running(monkeypatch, legacy_sqlite_db: Path):
    class FakeRQJob:
        id = "rq-test-1"

    class FakeQueue:
        def __init__(self):
            self.enqueued = []

        def enqueue(self, func, database_url, job_run_id):
            self.enqueued.append((func, database_url, job_run_id))
            return FakeRQJob()

    fake_queue = FakeQueue()

    from quant_trading.api.routes import jobs as jobs_route

    monkeypatch.setattr(jobs_route, "make_queue", lambda redis_url: fake_queue)
    settings = AppSettings(job_executor="rq", redis_url="redis://fake:6379/0")
    client, engine = make_client(settings=settings)

    response = client.post("/jobs/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["rq_job_id"] == "rq-test-1"
    assert fake_queue.enqueued[0][1] == settings.database_url
    with session_scope(engine) as session:
        row = session.get(JobRunORM, payload["id"])
        assert row.status == "queued"
        assert row.rq_job_id == "rq-test-1"


def test_jobs_require_auth_when_enabled():
    client, _ = make_client(AppSettings(require_auth=True, api_token="local-token"))

    response = client.get("/jobs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
```

- [ ] **Step 2: Verify API tests fail**

Run:

```bash
python -m pytest tests/integration/test_jobs_api.py -q
```

Expected: FAIL because `/jobs` routes and service do not exist.

- [ ] **Step 3: Implement job submission service**

Create `src/quant_trading/jobs/service.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy import Engine

from quant_trading.config import AppSettings
from quant_trading.jobs.runtime import execute_job_run, execute_job_run_with_engine, job_payload_dumps, utcnow
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobRunORM
from quant_trading.storage.repositories import JobRunRepository


class QueueLike(Protocol):
    def enqueue(self, func: Callable[..., object], *args: object) -> object:
        ...


def submit_job_run(
    engine: Engine,
    settings: AppSettings,
    job_type: str,
    request_payload: dict[str, Any],
    queue_factory: Callable[[str], QueueLike],
) -> JobRunORM:
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(
            job_type=job_type,
            request_payload=job_payload_dumps(request_payload),
            queued_at=utcnow(),
        )
        job_run_id = row.id

    if settings.job_executor == "inline":
        execute_job_run_with_engine(engine, job_run_id)
    elif settings.job_executor == "rq":
        queue = queue_factory(settings.redis_url)
        rq_job = queue.enqueue(execute_job_run, settings.database_url, job_run_id)
        with session_scope(engine) as session:
            repo = JobRunRepository(session)
            row = repo.get(job_run_id)
            if row is not None:
                repo.mark_enqueued(row, rq_job_id=str(rq_job.id), updated_at=utcnow())
    else:
        raise ValueError(f"unsupported job executor: {settings.job_executor}")

    with session_scope(engine) as session:
        row = JobRunRepository(session).get(job_run_id)
        if row is None:
            raise ValueError(f"job run not found after submit: {job_run_id}")
        session.expunge(row)
        return row
```

- [ ] **Step 4: Implement jobs API router**

Create `src/quant_trading/api/routes/jobs.py`:

```python
from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from quant_trading.api.routes.workflows import ImportLegacyRequest, MACrossBacktestRequest
from quant_trading.jobs.queue import make_queue
from quant_trading.jobs.runtime import BACKTEST_MA_CROSS, IMPORT_LEGACY, PAPER_RUN_TICK
from quant_trading.jobs.service import submit_job_run
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobRunORM
from quant_trading.storage.repositories import JobRunRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/import-legacy")
def create_import_job(payload: ImportLegacyRequest, request: Request) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            IMPORT_LEGACY,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )


@router.post("/backtests/ma-cross")
def create_backtest_job(payload: MACrossBacktestRequest, request: Request) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            BACKTEST_MA_CROSS,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )


@router.post("/paper/runs/{run_id}/tick")
def create_paper_tick_job(run_id: int, request: Request) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            PAPER_RUN_TICK,
            {"run_id": run_id},
            make_queue,
        )
    )


@router.get("")
def list_jobs(
    request: Request,
    status: str | None = None,
    job_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = JobRunRepository(session).list_recent(
            status=status,
            job_type=job_type,
            limit=limit,
        )
        return [_job_payload(row) for row in rows]


@router.get("/{job_run_id}")
def get_job(job_run_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = JobRunRepository(session).get(job_run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="job run not found")
        return _job_payload(row)


def _job_payload(row: JobRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_type": row.job_type,
        "status": row.status,
        "progress": row.progress,
        "request_payload": _json_loads(row.request_payload),
        "result_payload": _json_loads(row.result_payload),
        "error_message": row.error_message,
        "workflow_run_id": row.workflow_run_id,
        "rq_job_id": row.rq_job_id,
        "queued_at": _iso(row.queued_at),
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
```

Remove the unused `Queue` import if the editor reports it unused.

- [ ] **Step 5: Include jobs router**

Modify `src/quant_trading/api/main.py`.

Change route import:

```python
from quant_trading.api.routes import dashboard, backtests, health, instruments, jobs, paper, workflows
```

Add before `app.include_router(workflows.router)`:

```python
    app.include_router(jobs.router)
```

- [ ] **Step 6: Add auth regression coverage**

Append to `tests/integration/test_runtime_auth.py`:

```python
def test_jobs_api_requires_auth_when_enabled():
    client = make_client()

    response = client.get("/jobs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
```

- [ ] **Step 7: Verify API task**

Run:

```bash
python -m pytest tests/integration/test_jobs_api.py tests/integration/test_runtime_auth.py -q
python -m py_compile src/quant_trading/jobs/service.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/main.py
```

Expected: all commands exit 0.

- [ ] **Step 8: Spec review for Task 3**

Check:

```bash
rg -n "POST /jobs|GET /jobs|submit_job_run|QUANT_JOB_EXECUTOR|job_executor|make_queue|execute_job_run" docs/superpowers/specs/2026-06-23-quant-trading-queued-runtime-design.md src tests
```

Required evidence:

- API exposes all three job creation routes.
- API exposes list and detail read routes.
- RQ mode enqueues without executing inline.
- Jobs routes are protected by existing auth middleware.

- [ ] **Step 9: Quality review for Task 3**

Inspect:

- `submit_job_run()` owns executor choice; route handlers remain thin.
- RQ mode passes `settings.database_url` and `job_run_id` only.
- `limit` is clamped to `1..100`.
- No API token is stored in job payloads.

- [ ] **Step 10: Commit Task 3**

Run:

```bash
git add src/quant_trading/jobs/service.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/main.py tests/integration/test_jobs_api.py tests/integration/test_runtime_auth.py
git commit -m "feat: expose job run APIs"
```

## Task 4: Dashboard, Compose, README, And Final Verification

**Files:**

- Modify: `src/quant_trading/api/routes/dashboard.py`
- Modify: `tests/integration/test_dashboard.py`
- Modify: `docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: Add failing dashboard job run test**

Append to `tests/integration/test_dashboard.py`:

```python
def test_dashboard_displays_job_runs(legacy_sqlite_db: Path):
    client, _ = make_client()
    response = client.post(
        "/jobs/import-legacy",
        json={"legacy_db_path": str(legacy_sqlite_db)},
    )

    dashboard = client.get("/dashboard")

    assert response.status_code == 200
    assert dashboard.status_code == 200
    html = dashboard.text
    assert "Job Runs" in html
    assert "import_legacy" in html
    assert "100%" in html
    assert "succeeded" in html
```

- [ ] **Step 2: Verify dashboard test fails**

Run:

```bash
python -m pytest tests/integration/test_dashboard.py::test_dashboard_displays_job_runs -q
```

Expected: FAIL because dashboard does not render job runs.

- [ ] **Step 3: Render job runs in dashboard**

Modify `src/quant_trading/api/routes/dashboard.py`.

Update model imports:

```python
    JobRunORM,
```

Update repository import:

```python
from quant_trading.storage.repositories import JobRunRepository, WorkflowRunRepository
```

In `_collect_state()`, add:

```python
            "job_runs": JobRunRepository(session).list_recent(limit=20),
```

In `_render_dashboard()`, render job runs after workflow runs:

```python
  {_workflow_runs_table(state)}
  {_job_runs_table(state)}
```

Add:

```python
def _job_runs_table(state: dict[str, Any]) -> str:
    return _table(
        "Job Runs",
        ["ID", "Type", "Status", "Progress", "Started", "Duration", "Workflow Run", "Error"],
        state["job_runs"],
        lambda r: [
            f"#{r.id}",
            r.job_type,
            r.status,
            f"{r.progress}%",
            r.started_at,
            f"{r.duration_ms} ms" if r.duration_ms is not None else "",
            f"#{r.workflow_run_id}" if r.workflow_run_id else "",
            r.error_message or "",
        ],
    )
```

- [ ] **Step 4: Verify dashboard tests pass**

Run:

```bash
python -m pytest tests/integration/test_dashboard.py tests/integration/test_jobs_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Update Docker Compose for RQ mode**

Modify `docker-compose.yml`.

Add to both `api.environment` and `worker.environment`:

```yaml
      QUANT_JOB_EXECUTOR: rq
```

Keep existing `DATABASE_URL` and `REDIS_URL`.

- [ ] **Step 6: Update README queued runtime docs**

Modify `README.md`.

Add `/jobs` endpoints to the API endpoint list:

```text
http://localhost:8000/jobs
http://localhost:8000/jobs/{job_run_id}
http://localhost:8000/jobs/import-legacy
http://localhost:8000/jobs/backtests/ma-cross
http://localhost:8000/jobs/paper/runs/{run_id}/tick
```

Add a section after `Production Runtime And Safety MVP`:

```markdown
## Queued Job Runtime

Stage 5 adds durable job lifecycle tracking through `job_runs`.

Executor modes:

| Variable | Default | Purpose |
| --- | --- | --- |
| `QUANT_JOB_EXECUTOR` | `inline` | `inline` executes immediately in-process; `rq` enqueues work for the Redis/RQ worker. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection used by RQ mode. |

Create an inline local import job:

```bash
curl -X POST http://127.0.0.1:8000/jobs/import-legacy \
  -H "Content-Type: application/json" \
  -d '{"legacy_db_path":"legacy/django_app/db.sqlite3"}'
```

Read jobs:

```bash
curl http://127.0.0.1:8000/jobs
curl http://127.0.0.1:8000/jobs/1
```

`job_runs` records queued/running/succeeded/failed status, progress, result payload, error message, optional RQ job id, and the linked `workflow_run_id`.

Docker Compose sets `QUANT_JOB_EXECUTOR=rq` so API requests enqueue jobs and the worker executes them. This still does not place broker or exchange orders.
```

Also update the current milestone bullets to mention queued job lifecycle tracking.

- [ ] **Step 7: Verify docs and compose**

Run:

```bash
docker compose config
git diff --check README.md docker-compose.yml src/quant_trading/api/routes/dashboard.py tests/integration/test_dashboard.py
```

Expected: both commands exit 0.

- [ ] **Step 8: Focused Stage 5 verification**

Run:

```bash
python -m pytest tests/unit/test_settings.py tests/integration/test_migrations.py tests/integration/test_job_runs_repository.py tests/integration/test_workflow_runner.py tests/integration/test_job_runtime.py tests/integration/test_jobs_api.py tests/integration/test_dashboard.py tests/integration/test_runtime_auth.py -q
python -m py_compile src/quant_trading/config.py src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py src/quant_trading/workflows/runner.py src/quant_trading/jobs/runtime.py src/quant_trading/jobs/service.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/routes/dashboard.py src/quant_trading/api/main.py
```

Expected: all commands exit 0.

- [ ] **Step 9: Full verification**

Run:

```bash
python -m pytest -q
docker compose config
git status --short --branch
```

Expected:

- Pytest exits 0.
- Docker Compose config exits 0.
- Worktree only contains intended Stage 5 changes before commit, then clean after commit.

- [ ] **Step 10: Spec review for Task 4 and full Stage 5**

Review `docs/superpowers/specs/2026-06-23-quant-trading-queued-runtime-design.md` against implementation evidence:

- `job_runs` is the lifecycle source of truth.
- `workflow_runs` remains the command audit trail.
- `/jobs/...` routes exist for import, MA Cross backtest, and paper tick.
- `GET /jobs` and `GET /jobs/{job_run_id}` exist.
- Dashboard renders recent jobs.
- RQ mode enqueues instead of executing in API process.
- Inline mode executes deterministically.
- Safety boundary remains paper trading only.

- [ ] **Step 11: Quality review for Task 4 and full Stage 5**

Inspect:

- No real broker/exchange order path was added.
- Job execution code has one dispatch location.
- API route handlers stay thin.
- Worker entrypoint has no web request dependency.
- Failure messages are capped and generic enough for operational display.
- Existing `/workflows/...` routes still work.

- [ ] **Step 12: Commit Task 4**

Run:

```bash
git add README.md docker-compose.yml src/quant_trading/api/routes/dashboard.py tests/integration/test_dashboard.py
git commit -m "docs: document queued job runtime"
```

## Final Stage 5 Completion

After all four task commits:

```bash
python -m pytest -q
docker compose config
git log --oneline --decorate -8
git status --short --branch
```

Expected:

- Test suite exits 0.
- Compose config exits 0.
- Recent log contains the four Stage 5 implementation commits after the spec and plan commits.
- Worktree is clean.

Then use `superpowers:verification-before-completion` before making any completion claim, and follow AGENTS.md with a final Spec review and Quality review summary.
