# Quant Trading Scheduler Leases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add database-backed leases to scheduled operations so concurrent scheduler ticks cannot submit the same due schedule.

**Architecture:** Keep SQLAlchemy/Alembic as the source of truth. Add nullable lease diagnostics to `job_schedules`, acquire leases with a conditional repository update, and make `run_due_schedules()` submit only schedules it has claimed. Expose lease state through existing schedule API/dashboard responses without adding a new scheduler dependency.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, Alembic, FastAPI, pytest, existing job runtime, fake queues for deterministic tests.

---

## Baseline

```bash
cd /private/tmp/quant-stage4-runtime
git status --short --branch
```

Expected: branch `codex/quant-stage4-runtime-tmp`; worktree is clean after the design commit.

Primary design: `docs/superpowers/specs/2026-06-23-quant-trading-scheduler-leases-design.md`

## File Structure

Create:

- `migrations/versions/20260623_0005_add_scheduler_leases.py` - Alembic migration adding lease columns and index.

Modify:

- `src/quant_trading/storage/models.py` - add nullable lease columns to `JobScheduleORM`.
- `src/quant_trading/storage/repositories.py` - add due filtering, lease acquisition, and lease clearing methods.
- `src/quant_trading/jobs/schedules.py` - claim schedules before submission and release leases on success or failure.
- `src/quant_trading/api/routes/schedules.py` - include lease fields in schedule payloads.
- `src/quant_trading/api/routes/dashboard.py` - show compact lease diagnostics.
- `tests/integration/test_migrations.py` - assert migration creates lease columns.
- `tests/integration/test_job_schedules_repository.py` - cover lease acquisition/expiry/release.
- `tests/integration/test_job_schedules_service.py` - cover scheduler duplicate prevention and failure release.
- `tests/integration/test_schedules_api.py` - cover API lease fields.
- `tests/integration/test_dashboard.py` - cover dashboard lease state.
- `README.md` - document scheduler lease behavior and multi-instance guidance.

## Task 1: Schema And Migration

**Files:**

- Modify: `tests/integration/test_migrations.py`
- Create: `migrations/versions/20260623_0005_add_scheduler_leases.py`
- Modify: `src/quant_trading/storage/models.py`

- [ ] **Step 1: Write failing migration test**

Modify `tests/integration/test_migrations.py`:

```python
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_head_creates_runtime_schema(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "runtime.sqlite3"
    database_url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert "workflow_runs" in tables
    assert "job_runs" in tables
    assert "job_events" in tables
    assert "job_schedules" in tables
    assert "data_sync_runs" in tables
    assert "instruments" in tables
    assert "market_bars" in tables
    assert "backtest_runs" in tables
    assert "paper_accounts" in tables
    assert "paper_runs" in tables

    schedule_columns = {column["name"] for column in inspector.get_columns("job_schedules")}
    assert {"locked_until", "locked_by", "lock_acquired_at"} <= schedule_columns
```

- [ ] **Step 2: Run migration test to verify it fails**

Run:

```bash
python -m pytest tests/integration/test_migrations.py -q
```

Expected: FAIL because `job_schedules` does not include lease columns.

- [ ] **Step 3: Add ORM lease columns**

Modify `src/quant_trading/storage/models.py` inside `JobScheduleORM` after `last_job_run_id`:

```python
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lock_acquired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 4: Add Alembic migration**

Create `migrations/versions/20260623_0005_add_scheduler_leases.py`:

```python
"""add scheduler leases

Revision ID: 20260623_0005
Revises: 20260623_0004
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0005"
down_revision = "20260623_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_schedules", sa.Column("locked_until", sa.DateTime(), nullable=True))
    op.add_column("job_schedules", sa.Column("locked_by", sa.String(length=128), nullable=True))
    op.add_column("job_schedules", sa.Column("lock_acquired_at", sa.DateTime(), nullable=True))
    op.create_index("ix_job_schedules_locked_until", "job_schedules", ["locked_until"])


def downgrade() -> None:
    op.drop_index("ix_job_schedules_locked_until", table_name="job_schedules")
    op.drop_column("job_schedules", "lock_acquired_at")
    op.drop_column("job_schedules", "locked_by")
    op.drop_column("job_schedules", "locked_until")
```

- [ ] **Step 5: Verify schema task**

Run:

```bash
python -m pytest tests/integration/test_migrations.py -q
python -m py_compile src/quant_trading/storage/models.py migrations/versions/20260623_0005_add_scheduler_leases.py
```

Expected: PASS.

- [ ] **Step 6: Spec and quality review**

Spec review:

- Confirm migration adds exactly `locked_until`, `locked_by`, and `lock_acquired_at`.
- Confirm no unrelated tables or broker behavior changed.

Quality review:

- Confirm nullable columns preserve backward compatibility.
- Confirm `locked_until` is indexed.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_migrations.py src/quant_trading/storage/models.py migrations/versions/20260623_0005_add_scheduler_leases.py
git commit -m "feat: add scheduler lease schema"
```

## Task 2: Repository Lease Operations

**Files:**

- Modify: `tests/integration/test_job_schedules_repository.py`
- Modify: `src/quant_trading/storage/repositories.py`

- [ ] **Step 1: Write failing repository tests**

Append to `tests/integration/test_job_schedules_repository.py`:

```python
def test_job_schedule_repository_acquires_and_blocks_active_lease():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        row = repo.create(
            name="leased-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload="{}",
            schedule_type="interval",
            interval_seconds=3600,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        assert repo.acquire_due_lease(1, now=now, lease_until=now + timedelta(minutes=5), locked_by="runner-a") is True
        row = repo.get(1)
        assert row.locked_by == "runner-a"
        assert row.lock_acquired_at == now
        assert row.locked_until == now + timedelta(minutes=5)

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        assert repo.acquire_due_lease(1, now=now, lease_until=now + timedelta(minutes=5), locked_by="runner-b") is False


def test_job_schedule_repository_reclaims_expired_lease_and_clears_on_submit():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        row = repo.create(
            name="expired-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload="{}",
            schedule_type="interval",
            interval_seconds=3600,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )
        row.locked_until = now - timedelta(seconds=1)
        row.locked_by = "dead-runner"
        row.lock_acquired_at = now - timedelta(minutes=10)
        session.flush()

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        assert repo.acquire_due_lease(1, now=now, lease_until=now + timedelta(minutes=5), locked_by="runner-c") is True
        row = repo.get(1)
        repo.mark_submitted(row, job_run_id=42, ran_at=now, next_run_at=now + timedelta(hours=1))
        assert row.locked_until is None
        assert row.locked_by is None
        assert row.lock_acquired_at is None
```

- [ ] **Step 2: Run repository tests to verify they fail**

Run:

```bash
python -m pytest tests/integration/test_job_schedules_repository.py -q
```

Expected: FAIL because `acquire_due_lease()` does not exist.

- [ ] **Step 3: Implement repository lease operations**

Modify `src/quant_trading/storage/repositories.py` imports:

```python
from sqlalchemy import and_, or_, select, update
```

Modify `JobScheduleRepository.mark_submitted()` to clear lease fields:

```python
    def mark_submitted(
        self,
        row: JobScheduleORM,
        job_run_id: int,
        ran_at: datetime,
        next_run_at: datetime,
    ) -> JobScheduleORM:
        row.last_run_at = ran_at
        row.last_job_run_id = job_run_id
        row.next_run_at = next_run_at
        row.locked_until = None
        row.locked_by = None
        row.lock_acquired_at = None
        row.updated_at = ran_at
        self.session.flush()
        return row
```

Add methods to `JobScheduleRepository`:

```python
    def acquire_due_lease(
        self,
        schedule_id: int,
        *,
        now: datetime,
        lease_until: datetime,
        locked_by: str,
    ) -> bool:
        result = self.session.execute(
            update(JobScheduleORM)
            .where(JobScheduleORM.id == schedule_id)
            .where(JobScheduleORM.enabled.is_(True))
            .where(JobScheduleORM.next_run_at <= now)
            .where(
                or_(
                    JobScheduleORM.locked_until.is_(None),
                    JobScheduleORM.locked_until <= now,
                )
            )
            .values(
                locked_until=lease_until,
                locked_by=locked_by[:128],
                lock_acquired_at=now,
                updated_at=now,
            )
        )
        self.session.flush()
        return result.rowcount == 1

    def clear_lease(self, row: JobScheduleORM, updated_at: datetime) -> JobScheduleORM:
        row.locked_until = None
        row.locked_by = None
        row.lock_acquired_at = None
        row.updated_at = updated_at
        self.session.flush()
        return row
```

Modify `list_due()` to skip actively leased rows:

```python
    def list_due(self, now: datetime) -> list[JobScheduleORM]:
        return list(
            self.session.scalars(
                select(JobScheduleORM)
                .where(JobScheduleORM.enabled.is_(True))
                .where(JobScheduleORM.next_run_at <= now)
                .where(
                    or_(
                        JobScheduleORM.locked_until.is_(None),
                        JobScheduleORM.locked_until <= now,
                    )
                )
                .order_by(JobScheduleORM.next_run_at, JobScheduleORM.id)
            ).all()
        )
```

- [ ] **Step 4: Verify repository task**

Run:

```bash
python -m pytest tests/integration/test_job_schedules_repository.py -q
python -m py_compile src/quant_trading/storage/repositories.py
```

Expected: PASS.

- [ ] **Step 5: Spec and quality review**

Spec review:

- Confirm active leases block acquisition.
- Confirm expired leases can be reclaimed.
- Confirm successful submission clears lease fields.

Quality review:

- Confirm lease acquisition is one conditional SQL update.
- Confirm `locked_by` is capped to fit the column.
- Confirm disabled/future schedules remain unclaimable through the conditional update.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_job_schedules_repository.py src/quant_trading/storage/repositories.py
git commit -m "feat: add scheduler lease repository operations"
```

## Task 3: Scheduler Service Lease Enforcement

**Files:**

- Modify: `tests/integration/test_job_schedules_service.py`
- Modify: `src/quant_trading/jobs/schedules.py`

- [ ] **Step 1: Write failing service tests**

Append to `tests/integration/test_job_schedules_service.py`:

```python
class CountingQueue:
    def __init__(self):
        self.enqueued = 0

    def enqueue(self, func, *args):
        self.enqueued += 1
        return FakeQueueJob()


def test_run_due_schedules_skips_schedule_with_active_lease():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    create_job_schedule(
        engine,
        "active-lease-sync",
        MARKET_DATA_SYNC,
        {"provider": "akshare", "symbol": "000001"},
        3600,
        now,
    )
    with session_scope(engine) as session:
        schedule = JobScheduleRepository(session).get_by_name("active-lease-sync")
        schedule.locked_until = now + timedelta(minutes=5)
        schedule.locked_by = "runner-a"
        schedule.lock_acquired_at = now
        session.flush()

    queue = CountingQueue()
    submitted = run_due_schedules(
        engine,
        AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"),
        now,
        lambda url: queue,
        scheduler_id="runner-b",
    )

    assert submitted == []
    assert queue.enqueued == 0


def test_run_due_schedules_releases_lease_when_queue_submit_fails():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    create_job_schedule(
        engine,
        "failing-submit-sync",
        MARKET_DATA_SYNC,
        {"provider": "akshare", "symbol": "000001"},
        3600,
        now,
    )

    class FailingQueue:
        def enqueue(self, func, *args):
            raise RuntimeError("queue unavailable")

    with pytest.raises(RuntimeError, match="queue unavailable"):
        run_due_schedules(
            engine,
            AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"),
            now,
            lambda url: FailingQueue(),
            scheduler_id="runner-fail",
            lease_seconds=60,
        )

    with session_scope(engine) as session:
        schedule = JobScheduleRepository(session).get_by_name("failing-submit-sync")
        assert schedule.locked_until is None
        assert schedule.locked_by is None
        assert schedule.lock_acquired_at is None
        assert schedule.last_job_run_id is None
        assert schedule.next_run_at == now
```

- [ ] **Step 2: Run service tests to verify they fail**

Run:

```bash
python -m pytest tests/integration/test_job_schedules_service.py -q
```

Expected: FAIL because `run_due_schedules()` does not accept `scheduler_id` and does not release a lease on failure.

- [ ] **Step 3: Implement scheduler lease enforcement**

Modify `src/quant_trading/jobs/schedules.py` imports:

```python
from datetime import UTC, datetime, timedelta
import json
import socket
from typing import Any
```

Modify `run_due_schedules()` signature and implementation:

```python
def run_due_schedules(
    engine: Engine,
    settings: AppSettings,
    now: datetime,
    queue_factory,
    *,
    scheduler_id: str | None = None,
    lease_seconds: int = 300,
) -> list[dict[str, Any]]:
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be at least 1")
    locked_by = (scheduler_id or _default_scheduler_id())[:128]
    lease_until = now + timedelta(seconds=lease_seconds)

    with session_scope(engine) as session:
        due_ids = [row.id for row in JobScheduleRepository(session).list_due(now)]

    submitted: list[dict[str, Any]] = []
    for schedule_id in due_ids:
        with session_scope(engine) as session:
            repo = JobScheduleRepository(session)
            if not repo.acquire_due_lease(
                schedule_id,
                now=now,
                lease_until=lease_until,
                locked_by=locked_by,
            ):
                continue
            schedule = repo.get(schedule_id)
            if schedule is None:
                continue
            payload = _loads_payload(schedule.request_payload)
            next_run_at = _advance_interval(
                schedule.next_run_at,
                schedule.interval_seconds,
                now,
            )
            schedule_name = schedule.name
            job_type = schedule.job_type

        try:
            row = submit_job_run(engine, settings, job_type, payload, queue_factory)
        except Exception:
            with session_scope(engine) as session:
                repo = JobScheduleRepository(session)
                schedule = repo.get(schedule_id)
                if schedule is not None:
                    repo.clear_lease(schedule, updated_at=_utcnow())
            raise

        with session_scope(engine) as session:
            repo = JobScheduleRepository(session)
            schedule = repo.get(schedule_id)
            if schedule is not None:
                repo.mark_submitted(schedule, row.id, ran_at=now, next_run_at=next_run_at)
        submitted.append(
            {
                "schedule_id": schedule_id,
                "schedule_name": schedule_name,
                "job_run_id": row.id,
            }
        )
    return submitted
```

Add helper:

```python
def _default_scheduler_id() -> str:
    return f"{socket.gethostname()}:scheduler"
```

- [ ] **Step 4: Verify scheduler service task**

Run:

```bash
python -m pytest tests/integration/test_job_schedules_service.py tests/integration/test_job_schedules_repository.py -q
python -m py_compile src/quant_trading/jobs/schedules.py
```

Expected: PASS.

- [ ] **Step 5: Spec and quality review**

Spec review:

- Confirm only claimed schedules submit jobs.
- Confirm actively leased schedules are skipped.
- Confirm failed submit releases leases and propagates the error.

Quality review:

- Confirm public positional API remains backward compatible.
- Confirm no real Redis or provider dependency is introduced.
- Confirm lease protects the scheduler submission window without holding a DB transaction across job submission.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_job_schedules_service.py src/quant_trading/jobs/schedules.py
git commit -m "feat: enforce scheduler leases"
```

## Task 4: API, Dashboard, Docs, And Final Verification

**Files:**

- Modify: `tests/integration/test_schedules_api.py`
- Modify: `tests/integration/test_dashboard.py`
- Modify: `src/quant_trading/api/routes/schedules.py`
- Modify: `src/quant_trading/api/routes/dashboard.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing API and dashboard assertions**

Modify `tests/integration/test_schedules_api.py` in `test_schedule_api_create_list_patch_and_get_missing()`:

```python
    body = created.json()
    assert body["locked_until"] is None
    assert body["locked_by"] is None
    assert body["lock_acquired_at"] is None
```

Append to `tests/integration/test_dashboard.py`:

```python
def test_dashboard_displays_schedule_lease_state():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    with session_scope(engine) as session:
        schedule = JobScheduleRepository(session).create(
            name="leased-dashboard-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload="{}",
            schedule_type="interval",
            interval_seconds=3600,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )
        schedule.locked_until = now + timedelta(minutes=5)
        schedule.locked_by = "dashboard-runner"
        schedule.lock_acquired_at = now
        session.flush()

    client = TestClient(create_app(engine=engine))
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "dashboard-runner" in response.text
    assert "Lease" in response.text
```

Ensure `datetime`, `timedelta`, `session_scope`, `JobScheduleRepository`, and `MARKET_DATA_SYNC` imports exist in the test file before adding duplicates.

- [ ] **Step 2: Run API/dashboard tests to verify they fail**

Run:

```bash
python -m pytest tests/integration/test_schedules_api.py tests/integration/test_dashboard.py -q
```

Expected: FAIL because schedule payloads and dashboard do not expose lease state yet.

- [ ] **Step 3: Expose lease fields in schedule API**

Modify `_schedule_payload()` in `src/quant_trading/api/routes/schedules.py`:

```python
        "locked_until": row.locked_until.isoformat() if row.locked_until else None,
        "locked_by": row.locked_by,
        "lock_acquired_at": row.lock_acquired_at.isoformat() if row.lock_acquired_at else None,
```

- [ ] **Step 4: Render lease state in dashboard**

Modify `_job_schedules_table()` in `src/quant_trading/api/routes/dashboard.py` so the headers include `Lease` and each row includes `_format_schedule_lease(r)`:

```python
def _job_schedules_table(state: dict[str, Any]) -> str:
    return _table(
        "Job Schedules",
        ["ID", "Name", "Type", "Enabled", "Interval", "Next Run", "Last Run", "Last Job", "Lease"],
        state["job_schedules"],
        lambda r: [
            f"#{r.id}",
            r.name,
            r.job_type,
            "yes" if r.enabled else "no",
            f"{r.interval_seconds}s",
            r.next_run_at,
            r.last_run_at or "",
            f"#{r.last_job_run_id}" if r.last_job_run_id else "",
            _format_schedule_lease(r),
        ],
    )
```

Add helper:

```python
def _format_schedule_lease(row: JobScheduleORM) -> str:
    if row.locked_until is None:
        return ""
    owner = row.locked_by or "unknown"
    return f"{owner} until {row.locked_until}"
```

- [ ] **Step 5: Update README**

In `README.md` under `Scheduled Operations And Job Control`, add:

```markdown
Scheduler ticks use database-backed leases on `job_schedules` (`locked_until`, `locked_by`, and `lock_acquired_at`) so multiple scheduler runners do not submit the same due schedule at the same time. Expired leases are reclaimable on a later tick, which lets the system recover from a scheduler process crash between claim and release.

For production-like deployments, run scheduled operations through the queued executor (`QUANT_JOB_EXECUTOR=rq`). The lease protects schedule submission; job execution remains handled by the worker.
```

Remove or update any roadmap line that says high-availability schedule locking is still missing.

- [ ] **Step 6: Verify API/dashboard/docs task**

Run:

```bash
python -m pytest tests/integration/test_schedules_api.py tests/integration/test_dashboard.py tests/integration/test_runtime_auth.py -q
python -m py_compile src/quant_trading/api/routes/schedules.py src/quant_trading/api/routes/dashboard.py
rg -n "locked_until|locked_by|lock_acquired_at|database-backed leases|high-availability schedule locking" README.md src tests docs/superpowers/specs/2026-06-23-quant-trading-scheduler-leases-design.md
```

Expected: tests and py_compile PASS. `rg` shows lease fields documented and implemented; no roadmap claim says HA schedule locking is still missing.

- [ ] **Step 7: Spec and quality review**

Spec review:

- Confirm API exposes lease fields.
- Confirm dashboard displays lease diagnostics.
- Confirm README explains lease scope and RQ guidance.

Quality review:

- Confirm dashboard uses existing server-rendered table helpers.
- Confirm no credentials or provider payloads are displayed.
- Confirm route compatibility is preserved.

- [ ] **Step 8: Final verification**

Run:

```bash
python -m pytest -q
python -m py_compile src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py src/quant_trading/jobs/schedules.py src/quant_trading/api/routes/schedules.py src/quant_trading/api/routes/dashboard.py migrations/versions/20260623_0005_add_scheduler_leases.py
docker compose config
git diff --check
git status --short --branch
```

Expected: full suite PASS; py_compile PASS; compose config exits 0; diff check exits 0; git status shows only intended uncommitted files before commit.

- [ ] **Step 9: Commit**

```bash
git add tests/integration/test_schedules_api.py tests/integration/test_dashboard.py src/quant_trading/api/routes/schedules.py src/quant_trading/api/routes/dashboard.py README.md
git commit -m "docs: document scheduler leases"
```

## Plan Self-Review

- Spec coverage: migration/ORM, repository atomic lease, service enforcement, expired lease recovery, failure release, API/dashboard diagnostics, README, and verification are all covered.
- Placeholder scan: no TBD/TODO/fill-in placeholders are used.
- Type consistency: lease fields are consistently named `locked_until`, `locked_by`, and `lock_acquired_at`; service parameters are `scheduler_id` and `lease_seconds`.

Plan complete and saved to `docs/superpowers/plans/2026-06-23-quant-trading-scheduler-leases.md`.

Execution recommendation: use inline execution with `superpowers:executing-plans` in this existing worktree, because the current branch already contains the staged productization commits and the task is tightly coupled across schema, repository, service, API, and docs.
