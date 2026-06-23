# Quant Trading Scheduled Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add interval market-data schedules, job event timelines, and explicit cancellation controls to the existing queued job runtime.

**Architecture:** Keep the database as the operational source of truth. Add `job_events` and `job_schedules`, then layer lifecycle event recording, cooperative cancellation, and explicit scheduler ticks over the existing `job_runs`, inline executor, and RQ executor. Use an explicit `run_due_schedules()` tick rather than a long-running scheduler dependency.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, pytest/TestClient, existing inline/RQ runtime, fake providers and fake queues for deterministic tests.

---

## Baseline

```bash
cd /private/tmp/quant-stage4-runtime
git status --short --branch
```

Expected: branch `codex/quant-stage4-runtime-tmp`; Stage 6 and Stage 7 design commits are local; this plan file is the only uncommitted file before implementation starts.

Primary design: `docs/superpowers/specs/2026-06-23-quant-trading-scheduled-operations-design.md`

## File Structure

Create:

- `migrations/versions/20260623_0004_add_scheduled_operations.py` - Alembic migration for `job_events` and `job_schedules`.
- `src/quant_trading/jobs/cancellation.py` - `JobCancelled`, cooperative token, and cancellation service.
- `src/quant_trading/jobs/schedules.py` - schedule validation, CRUD helpers, interval advancement, and `run_due_schedules()`.
- `src/quant_trading/api/routes/schedules.py` - schedule CRUD and scheduler tick API.
- `tests/integration/test_job_events_repository.py` - event repository coverage.
- `tests/integration/test_job_schedules_repository.py` - schedule repository coverage.
- `tests/integration/test_job_events_runtime.py` - lifecycle and cancellation coverage.
- `tests/integration/test_job_schedules_service.py` - scheduler service coverage.
- `tests/integration/test_schedules_api.py` - schedule API coverage.

Modify:

- `src/quant_trading/storage/models.py` - add `JobEventORM` and `JobScheduleORM`.
- `src/quant_trading/storage/repositories.py` - add event/schedule repositories and cancellation state transitions.
- `src/quant_trading/jobs/runtime.py` - record lifecycle events and pass cancellation/progress hooks.
- `src/quant_trading/jobs/service.py` - record queued/enqueued events.
- `src/quant_trading/data/sync.py` - add progress callback and cooperative cancellation checkpoints.
- `src/quant_trading/api/routes/jobs.py` - add job cancellation and event timeline routes.
- `src/quant_trading/api/main.py` - include schedules router.
- `src/quant_trading/api/routes/dashboard.py` - show schedules and recent job events.
- `tests/integration/test_migrations.py` - assert new tables exist.
- `tests/integration/test_jobs_api.py` - cover cancellation and events APIs.
- `tests/integration/test_runtime_auth.py` - cover auth on new routes.
- `tests/integration/test_dashboard.py` - cover dashboard output.
- `README.md` - document scheduled operations and safety boundaries.

## Task 1: Storage And Migration

**Files:**

- Modify: `src/quant_trading/storage/models.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `migrations/versions/20260623_0004_add_scheduled_operations.py`
- Modify: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_job_events_repository.py`
- Create: `tests/integration/test_job_schedules_repository.py`

- [ ] **Step 1: Write failing event repository test**

Create `tests/integration/test_job_events_repository.py`:

```python
from datetime import UTC, datetime
import json

from quant_trading.jobs.runtime import IMPORT_LEGACY, job_payload_dumps
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobEventORM
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_job_event_repository_records_and_lists_timeline():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        job = JobRunRepository(session).create_queued(
            IMPORT_LEGACY,
            job_payload_dumps({"legacy_db_path": "legacy.sqlite3"}),
            now,
        )
        repo = JobEventRepository(session)
        repo.record(job.id, "queued", "job queued", progress=0, payload={"source": "api"}, created_at=now)
        repo.record(job.id, "running", "job started", progress=10, payload={}, created_at=now)

    with session_scope(engine) as session:
        rows = JobEventRepository(session).list_for_job(1)
        recent = JobEventRepository(session).list_recent(limit=1)
        raw = session.get(JobEventORM, 1)

        assert [event.event_type for event in rows] == ["queued", "running"]
        assert [event.event_type for event in recent] == ["running"]
        assert raw.message == "job queued"
        assert raw.progress == 0
        assert json.loads(raw.payload) == {"source": "api"}
```

- [ ] **Step 2: Write failing schedule repository test**

Create `tests/integration/test_job_schedules_repository.py`:

```python
from datetime import UTC, datetime, timedelta
import json

from quant_trading.jobs.runtime import MARKET_DATA_SYNC, job_payload_dumps
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobScheduleORM
from quant_trading.storage.repositories import JobScheduleRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_job_schedule_repository_creates_filters_and_advances_schedule():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        row = repo.create(
            name="daily-000001-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload=job_payload_dumps({"provider": "fake", "symbol": "000001"}),
            schedule_type="interval",
            interval_seconds=86400,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )
        repo.mark_submitted(row, job_run_id=7, ran_at=now, next_run_at=now + timedelta(days=1))

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        due = repo.list_due(now + timedelta(hours=1))
        filtered = repo.list_recent(enabled=True, job_type=MARKET_DATA_SYNC)
        row = session.get(JobScheduleORM, 1)

        assert due == []
        assert [schedule.name for schedule in filtered] == ["daily-000001-sync"]
        assert row.last_job_run_id == 7
        assert row.next_run_at == now + timedelta(days=1)
        assert json.loads(row.request_payload) == {"provider": "fake", "symbol": "000001"}


def test_job_schedule_repository_can_disable_and_get_by_name():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        row = repo.create(
            name="disabled-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload="{}",
            schedule_type="interval",
            interval_seconds=3600,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )
        repo.update(row, enabled=False, updated_at=now)

    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        assert repo.get_by_name("disabled-sync").enabled is False
        assert repo.list_due(now) == []
```

- [ ] **Step 3: Verify tests fail**

Run:

```bash
python -m pytest tests/integration/test_job_events_repository.py tests/integration/test_job_schedules_repository.py -q
```

Expected: FAIL because `JobEventORM`, `JobScheduleORM`, `JobEventRepository`, and `JobScheduleRepository` do not exist.

- [ ] **Step 4: Add ORM models**

Modify `src/quant_trading/storage/models.py`. Add `Boolean` to SQLAlchemy imports and insert after `JobRunORM`:

```python
class JobEventORM(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_run_id: Mapped[int] = mapped_column(ForeignKey("job_runs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(String(512), default="")
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class JobScheduleORM(Base):
    __tablename__ = "job_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    request_payload: Mapped[str] = mapped_column(Text, default="{}")
    schedule_type: Mapped[str] = mapped_column(String(32), default="interval")
    interval_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_job_run_id: Mapped[int | None] = mapped_column(ForeignKey("job_runs.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 5: Add repositories and job cancellation states**

Modify `src/quant_trading/storage/repositories.py`. Add `import json`, import `JobEventORM` and `JobScheduleORM`, append these methods to `JobRunRepository`:

```python
    def update_progress(self, row: JobRunORM, progress: int, updated_at: datetime) -> JobRunORM:
        row.progress = progress
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_cancel_requested(self, row: JobRunORM, updated_at: datetime) -> JobRunORM:
        row.status = "cancel_requested"
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_cancelled(self, row: JobRunORM, finished_at: datetime, duration_ms: int | None = None) -> JobRunORM:
        row.status = "cancelled"
        row.error_message = "cancelled"
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        row.updated_at = finished_at
        self.session.flush()
        return row
```

Append:

```python
class JobEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(self, job_run_id: int, event_type: str, message: str = "", *, progress: int | None = None, payload: dict | None = None, created_at: datetime) -> JobEventORM:
        row = JobEventORM(job_run_id=job_run_id, event_type=event_type, message=message, progress=progress, payload=json.dumps(payload or {}, sort_keys=True), created_at=created_at)
        self.session.add(row)
        self.session.flush()
        return row

    def list_for_job(self, job_run_id: int) -> list[JobEventORM]:
        return list(self.session.scalars(select(JobEventORM).where(JobEventORM.job_run_id == job_run_id).order_by(JobEventORM.id)).all())

    def list_recent(self, *, limit: int = 50) -> list[JobEventORM]:
        return list(self.session.scalars(select(JobEventORM).order_by(JobEventORM.id.desc()).limit(limit)).all())


class JobScheduleRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, name: str, job_type: str, request_payload: str, schedule_type: str, interval_seconds: int, enabled: bool, next_run_at: datetime, created_at: datetime) -> JobScheduleORM:
        row = JobScheduleORM(name=name, job_type=job_type, request_payload=request_payload, schedule_type=schedule_type, interval_seconds=interval_seconds, enabled=enabled, next_run_at=next_run_at, created_at=created_at, updated_at=created_at)
        self.session.add(row)
        self.session.flush()
        return row

    def update(self, row: JobScheduleORM, *, enabled: bool | None = None, request_payload: str | None = None, interval_seconds: int | None = None, next_run_at: datetime | None = None, updated_at: datetime) -> JobScheduleORM:
        if enabled is not None:
            row.enabled = enabled
        if request_payload is not None:
            row.request_payload = request_payload
        if interval_seconds is not None:
            row.interval_seconds = interval_seconds
        if next_run_at is not None:
            row.next_run_at = next_run_at
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_submitted(self, row: JobScheduleORM, job_run_id: int, ran_at: datetime, next_run_at: datetime) -> JobScheduleORM:
        row.last_run_at = ran_at
        row.last_job_run_id = job_run_id
        row.next_run_at = next_run_at
        row.updated_at = ran_at
        self.session.flush()
        return row

    def list_due(self, now: datetime) -> list[JobScheduleORM]:
        return list(self.session.scalars(select(JobScheduleORM).where(JobScheduleORM.enabled.is_(True)).where(JobScheduleORM.next_run_at <= now).order_by(JobScheduleORM.next_run_at, JobScheduleORM.id)).all())

    def list_recent(self, *, enabled: bool | None = None, job_type: str | None = None, limit: int = 50) -> list[JobScheduleORM]:
        statement = select(JobScheduleORM).order_by(JobScheduleORM.id.desc()).limit(limit)
        if enabled is not None:
            statement = statement.where(JobScheduleORM.enabled.is_(enabled))
        if job_type:
            statement = statement.where(JobScheduleORM.job_type == job_type)
        return list(self.session.scalars(statement).all())

    def get(self, schedule_id: int) -> JobScheduleORM | None:
        return self.session.get(JobScheduleORM, schedule_id)

    def get_by_name(self, name: str) -> JobScheduleORM | None:
        return self.session.scalar(select(JobScheduleORM).where(JobScheduleORM.name == name))
```

- [ ] **Step 6: Add migration and migration test**

Create `migrations/versions/20260623_0004_add_scheduled_operations.py`:

```python
from alembic import op
import sqlalchemy as sa

revision = "20260623_0004"
down_revision = "20260623_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("job_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("job_run_id", sa.Integer(), sa.ForeignKey("job_runs.id"), nullable=False), sa.Column("event_type", sa.String(length=32), nullable=False), sa.Column("message", sa.String(length=512), nullable=False, server_default=""), sa.Column("progress", sa.Integer(), nullable=True), sa.Column("payload", sa.Text(), nullable=False, server_default="{}"), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_job_events_job_run_id", "job_events", ["job_run_id"])
    op.create_index("ix_job_events_event_type", "job_events", ["event_type"])
    op.create_index("ix_job_events_created_at", "job_events", ["created_at"])
    op.create_table("job_schedules", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(length=128), nullable=False), sa.Column("job_type", sa.String(length=64), nullable=False), sa.Column("request_payload", sa.Text(), nullable=False, server_default="{}"), sa.Column("schedule_type", sa.String(length=32), nullable=False, server_default="interval"), sa.Column("interval_seconds", sa.Integer(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("next_run_at", sa.DateTime(), nullable=False), sa.Column("last_run_at", sa.DateTime(), nullable=True), sa.Column("last_job_run_id", sa.Integer(), sa.ForeignKey("job_runs.id"), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_job_schedules_name", "job_schedules", ["name"], unique=True)
    op.create_index("ix_job_schedules_job_type", "job_schedules", ["job_type"])
    op.create_index("ix_job_schedules_enabled", "job_schedules", ["enabled"])
    op.create_index("ix_job_schedules_next_run_at", "job_schedules", ["next_run_at"])
    op.create_index("ix_job_schedules_last_job_run_id", "job_schedules", ["last_job_run_id"])


def downgrade() -> None:
    op.drop_index("ix_job_schedules_last_job_run_id", table_name="job_schedules")
    op.drop_index("ix_job_schedules_next_run_at", table_name="job_schedules")
    op.drop_index("ix_job_schedules_enabled", table_name="job_schedules")
    op.drop_index("ix_job_schedules_job_type", table_name="job_schedules")
    op.drop_index("ix_job_schedules_name", table_name="job_schedules")
    op.drop_table("job_schedules")
    op.drop_index("ix_job_events_created_at", table_name="job_events")
    op.drop_index("ix_job_events_event_type", table_name="job_events")
    op.drop_index("ix_job_events_job_run_id", table_name="job_events")
    op.drop_table("job_events")
```

Append to `tests/integration/test_migrations.py`:

```python
    assert "job_events" in tables
    assert "job_schedules" in tables
```

- [ ] **Step 7: Verify, review, and commit Task 1**

Run:

```bash
python -m pytest tests/integration/test_job_events_repository.py tests/integration/test_job_schedules_repository.py tests/integration/test_migrations.py -q
python -m py_compile src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py
rg -n "job_events|job_schedules|cancel_requested|cancelled|list_due|mark_submitted" src/quant_trading/storage migrations tests/integration docs/superpowers/specs/2026-06-23-quant-trading-scheduled-operations-design.md
```

Expected: pytest and py_compile exit 0; grep shows storage coverage. Spec review: tables, indexes, event repository, schedule repository, and cancellation status transitions exist. Quality review: event payloads use `json.dumps(payload or {}, sort_keys=True)`, due filtering uses `.is_(True)`, no credentials or provider raw payloads are stored, repositories have no FastAPI dependency.

Commit:

```bash
git add src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260623_0004_add_scheduled_operations.py tests/integration/test_migrations.py tests/integration/test_job_events_repository.py tests/integration/test_job_schedules_repository.py
git commit -m "feat: add scheduled operations storage"
```

## Task 2: Runtime Events And Cancellation

**Files:**

- Create: `src/quant_trading/jobs/cancellation.py`
- Modify: `src/quant_trading/jobs/runtime.py`
- Modify: `src/quant_trading/jobs/service.py`
- Modify: `src/quant_trading/data/sync.py`
- Create: `tests/integration/test_job_events_runtime.py`
- Modify: `tests/integration/test_market_data_sync_service.py`
- Modify: `tests/integration/test_job_runtime.py`

- [ ] **Step 1: Write failing runtime tests**

Create `tests/integration/test_job_events_runtime.py`:

```python
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from quant_trading.config import AppSettings
from quant_trading.core.enums import Adjustment, Market
from quant_trading.core.models import Bar
from quant_trading.data.providers.base import MarketDataProvider
from quant_trading.data.providers.registry import ProviderRegistry
from quant_trading.data.sync import sync_daily_market_data
from quant_trading.jobs.cancellation import JobCancelled, cancel_job_run
from quant_trading.jobs.runtime import IMPORT_LEGACY, MARKET_DATA_SYNC, execute_job_run_with_engine, job_payload_dumps, utcnow
from quant_trading.jobs.service import submit_job_run
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository


class FakeQueueJob:
    id = "rq-1"


class FakeQueue:
    def enqueue(self, func, *args):
        return FakeQueueJob()


class FakeProvider(MarketDataProvider):
    name = "fake"

    def fetch_daily_bars(self, instrument_id, symbol, start, end):
        return [Bar(instrument_id=instrument_id, symbol=symbol, market=Market.A_STOCK, timestamp=date(2026, 6, 22), open=Decimal("10"), high=Decimal("11"), low=Decimal("9"), close=Decimal("10.5"), volume=Decimal("1000"), adjusted=Adjustment.QFQ, source="fake")]


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_submit_job_records_queued_and_enqueued_events():
    engine = make_engine_with_schema()
    row = submit_job_run(engine, AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"), IMPORT_LEGACY, {"legacy_db_path": "legacy.sqlite3"}, lambda url: FakeQueue())

    with session_scope(engine) as session:
        events = JobEventRepository(session).list_for_job(row.id)
        assert [event.event_type for event in events] == ["queued", "enqueued"]
        assert events[1].payload == '{"rq_job_id": "rq-1"}'


def test_cancel_queued_job_records_cancelled_event():
    engine = make_engine_with_schema()
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(IMPORT_LEGACY, "{}", utcnow())
        job_run_id = row.id

    cancelled = cancel_job_run(engine, job_run_id)

    assert cancelled.status == "cancelled"
    with session_scope(engine) as session:
        assert [event.event_type for event in JobEventRepository(session).list_for_job(job_run_id)] == ["cancelled"]


def test_execute_job_skips_pre_cancelled_job():
    engine = make_engine_with_schema()
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(IMPORT_LEGACY, job_payload_dumps({"legacy_db_path": "missing.sqlite3"}), utcnow())
        JobRunRepository(session).mark_cancelled(row, utcnow())
        job_run_id = row.id

    assert execute_job_run_with_engine(engine, job_run_id) == {"job_run_id": job_run_id, "status": "cancelled", "error_message": "cancelled"}


def test_market_sync_checks_cancellation_before_upsert():
    engine = make_engine_with_schema()
    registry = ProviderRegistry()
    registry.register(FakeProvider())
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(MARKET_DATA_SYNC, "{}", utcnow())
        JobRunRepository(session).mark_cancel_requested(row, utcnow())
        job_run_id = row.id

    with pytest.raises(JobCancelled):
        sync_daily_market_data(engine, "fake", "000001", "2026-06-22", "2026-06-22", registry=registry, job_run_id=job_run_id)
```

- [ ] **Step 2: Verify tests fail**

```bash
python -m pytest tests/integration/test_job_events_runtime.py -q
```

Expected: FAIL because cancellation module and event recording are not implemented.

- [ ] **Step 3: Add cancellation service**

Create `src/quant_trading/jobs/cancellation.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobRunORM
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class JobCancelled(Exception):
    pass


class CancellationToken:
    def __init__(self, engine: Engine, job_run_id: int | None):
        self.engine = engine
        self.job_run_id = job_run_id

    def raise_if_cancelled(self) -> None:
        if self.job_run_id is None:
            return
        with session_scope(self.engine) as session:
            row = JobRunRepository(session).get(self.job_run_id)
            if row is not None and row.status in {"cancel_requested", "cancelled"}:
                raise JobCancelled("cancelled")


def cancel_job_run(engine: Engine, job_run_id: int) -> JobRunORM:
    now = _utcnow()
    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        events = JobEventRepository(session)
        row = repo.get(job_run_id)
        if row is None:
            raise ValueError(f"job run not found: {job_run_id}")
        if row.status in TERMINAL_STATUSES:
            raise ValueError(f"cannot cancel terminal job: {row.status}")
        if row.status == "queued":
            repo.mark_cancelled(row, finished_at=now)
            events.record(row.id, "cancelled", "job cancelled before execution", progress=row.progress, created_at=now)
        else:
            repo.mark_cancel_requested(row, updated_at=now)
            events.record(row.id, "cancel_requested", "cancellation requested", progress=row.progress, created_at=now)
        session.expunge(row)
        return row


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
```

Do not import `utcnow` from `jobs.runtime`; that would create a circular import because runtime imports `CancellationToken`.

- [ ] **Step 4: Record lifecycle events**

Modify `src/quant_trading/jobs/service.py` to record `queued` after `create_queued()` and `enqueued` after `mark_enqueued()`:

```python
JobEventRepository(session).record(row.id, "queued", "job queued", progress=0, payload={"job_type": job_type}, created_at=utcnow())
JobEventRepository(session).record(row.id, "enqueued", "job enqueued", progress=row.progress, payload={"rq_job_id": str(rq_job.id)}, created_at=utcnow())
```

Modify `src/quant_trading/jobs/runtime.py`: import `Callable`, `CancellationToken`, `JobCancelled`, and `JobEventRepository`; skip rows already `cancelled`; record `running`, `progress`, `succeeded`, `failed`, and `cancelled` events. Add:

```python
def _record_progress(engine: Engine, job_run_id: int, progress: int, message: str) -> None:
    now = utcnow()
    with session_scope(engine) as session:
        repo = JobRunRepository(session)
        job = repo.get(job_run_id)
        if job is not None:
            repo.update_progress(job, progress=progress, updated_at=now)
            JobEventRepository(session).record(job.id, "progress", message, progress=progress, created_at=now)
```

Extend `_execute_payload()` with keyword-only `cancellation_token` and `progress_callback`, and pass them into `sync_daily_market_data()` for `MARKET_DATA_SYNC`.

- [ ] **Step 5: Add cooperative sync checkpoints**

Modify `src/quant_trading/data/sync.py`: import `Callable` and `CancellationToken`; extend `sync_daily_market_data()` with:

```python
cancellation_token: CancellationToken | None = None
progress_callback: Callable[[int, str], None] | None = None
```

Add cancellation checks before provider fetch, after validation, and before each bar upsert:

```python
def _check_cancelled(cancellation_token: CancellationToken | None) -> None:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()


def _emit_progress(progress_callback: Callable[[int, str], None] | None, progress: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(progress, message)
```

Use `_emit_progress(progress_callback, 20, "fetching provider bars")`, `_emit_progress(progress_callback, 50, "validated provider bars")`, and `_emit_progress(progress_callback, 90, "stored provider bars")`.

- [ ] **Step 6: Verify, review, and commit Task 2**

```bash
python -m pytest tests/integration/test_job_events_runtime.py tests/integration/test_market_data_sync_service.py tests/integration/test_job_runtime.py -q
python -m py_compile src/quant_trading/jobs/cancellation.py src/quant_trading/jobs/runtime.py src/quant_trading/jobs/service.py src/quant_trading/data/sync.py
rg -n "queued|enqueued|running|progress|cancel_requested|cancelled|succeeded|failed|CancellationToken|JobCancelled" src/quant_trading/jobs src/quant_trading/data tests/integration docs/superpowers/specs/2026-06-23-quant-trading-scheduled-operations-design.md
```

Expected: tests and py_compile exit 0; grep shows lifecycle coverage. Spec review: all lifecycle event types are recorded; queued jobs can be cancelled; running jobs can be marked `cancel_requested`; sync checks cancellation at required checkpoints. Quality review: `jobs.cancellation` does not import `jobs.runtime`; `JobCancelled` is caught before broad `Exception`; tests use fake queue/provider only.

Commit:

```bash
git add src/quant_trading/jobs/cancellation.py src/quant_trading/jobs/runtime.py src/quant_trading/jobs/service.py src/quant_trading/data/sync.py tests/integration/test_job_events_runtime.py tests/integration/test_market_data_sync_service.py tests/integration/test_job_runtime.py
git commit -m "feat: add job events and cancellation"
```

## Task 3: Schedule Service

**Files:**

- Create: `src/quant_trading/jobs/schedules.py`
- Create: `tests/integration/test_job_schedules_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/integration/test_job_schedules_service.py`:

```python
from datetime import datetime, timedelta

import pytest

from quant_trading.config import AppSettings
from quant_trading.jobs.runtime import MARKET_DATA_SYNC
from quant_trading.jobs.schedules import create_job_schedule, run_due_schedules
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import JobScheduleRepository


class FakeQueueJob:
    id = "rq-scheduled"


class FakeQueue:
    def enqueue(self, func, *args):
        return FakeQueueJob()


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_run_due_schedules_submits_once_and_advances_past_now():
    engine = make_engine_with_schema()
    now = datetime(2026, 6, 23, 9, 30)
    create_job_schedule(engine, "daily-000001-sync", MARKET_DATA_SYNC, {"provider": "akshare", "symbol": "000001"}, 3600, now - timedelta(hours=3))

    submitted = run_due_schedules(engine, AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"), now, lambda url: FakeQueue())

    assert len(submitted) == 1
    assert submitted[0]["schedule_name"] == "daily-000001-sync"
    with session_scope(engine) as session:
        schedule = JobScheduleRepository(session).get_by_name("daily-000001-sync")
        assert schedule.last_job_run_id == submitted[0]["job_run_id"]
        assert schedule.next_run_at == now + timedelta(hours=1)


def test_schedule_validation_rejects_unknown_job_type_and_short_interval():
    engine = make_engine_with_schema()
    with pytest.raises(ValueError, match="unsupported schedule job_type"):
        create_job_schedule(engine, "bad-type", "paper_run_tick", {}, 3600, datetime(2026, 6, 23))
    with pytest.raises(ValueError, match="interval_seconds must be at least 60"):
        create_job_schedule(engine, "too-fast", MARKET_DATA_SYNC, {}, 30, datetime(2026, 6, 23))
```

- [ ] **Step 2: Verify tests fail**

```bash
python -m pytest tests/integration/test_job_schedules_service.py -q
```

Expected: FAIL because `quant_trading.jobs.schedules` does not exist.

- [ ] **Step 3: Implement schedule service**

Create `src/quant_trading/jobs/schedules.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
import json

from sqlalchemy import Engine

from quant_trading.config import AppSettings
from quant_trading.jobs.runtime import MARKET_DATA_SYNC, job_payload_dumps
from quant_trading.jobs.service import submit_job_run
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobScheduleORM
from quant_trading.storage.repositories import JobScheduleRepository

SUPPORTED_SCHEDULE_JOB_TYPES = {MARKET_DATA_SYNC}


def create_job_schedule(engine: Engine, name: str, job_type: str, request_payload: dict[str, Any], interval_seconds: int, next_run_at: datetime, *, enabled: bool = True) -> JobScheduleORM:
    _validate_schedule(job_type, request_payload, interval_seconds)
    now = _utcnow()
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        if repo.get_by_name(name) is not None:
            raise ValueError(f"job schedule already exists: {name}")
        row = repo.create(name, job_type, job_payload_dumps(request_payload), "interval", interval_seconds, enabled, next_run_at, now)
        session.expunge(row)
        return row


def update_job_schedule(engine: Engine, schedule_id: int, *, enabled: bool | None = None, request_payload: dict[str, Any] | None = None, interval_seconds: int | None = None, next_run_at: datetime | None = None) -> JobScheduleORM:
    now = _utcnow()
    with session_scope(engine) as session:
        repo = JobScheduleRepository(session)
        row = repo.get(schedule_id)
        if row is None:
            raise ValueError(f"job schedule not found: {schedule_id}")
        payload_text = None
        if request_payload is not None:
            _validate_payload(request_payload)
            payload_text = job_payload_dumps(request_payload)
        if interval_seconds is not None and interval_seconds < 60:
            raise ValueError("interval_seconds must be at least 60")
        repo.update(row, enabled=enabled, request_payload=payload_text, interval_seconds=interval_seconds, next_run_at=next_run_at, updated_at=now)
        session.expunge(row)
        return row


def run_due_schedules(engine: Engine, settings: AppSettings, now: datetime, queue_factory) -> list[dict[str, Any]]:
    with session_scope(engine) as session:
        due_ids = [row.id for row in JobScheduleRepository(session).list_due(now)]
    submitted = []
    for schedule_id in due_ids:
        with session_scope(engine) as session:
            repo = JobScheduleRepository(session)
            schedule = repo.get(schedule_id)
            if schedule is None or not schedule.enabled or schedule.next_run_at > now:
                continue
            payload = _loads_payload(schedule.request_payload)
            next_run_at = _advance_interval(schedule.next_run_at, schedule.interval_seconds, now)
            schedule_name = schedule.name
            job_type = schedule.job_type
        row = submit_job_run(engine, settings, job_type, payload, queue_factory)
        with session_scope(engine) as session:
            schedule = JobScheduleRepository(session).get(schedule_id)
            if schedule is not None:
                JobScheduleRepository(session).mark_submitted(schedule, row.id, ran_at=now, next_run_at=next_run_at)
        submitted.append({"schedule_id": schedule_id, "schedule_name": schedule_name, "job_run_id": row.id})
    return submitted


def _validate_schedule(job_type: str, request_payload: dict[str, Any], interval_seconds: int) -> None:
    if job_type not in SUPPORTED_SCHEDULE_JOB_TYPES:
        raise ValueError(f"unsupported schedule job_type: {job_type}")
    _validate_payload(request_payload)
    if interval_seconds < 60:
        raise ValueError("interval_seconds must be at least 60")


def _validate_payload(request_payload: dict[str, Any]) -> None:
    if not isinstance(request_payload, dict):
        raise ValueError("request_payload must be an object")


def _loads_payload(value: str) -> dict[str, Any]:
    loaded = json.loads(value or "{}")
    if not isinstance(loaded, dict):
        raise ValueError("request_payload must be an object")
    return loaded


def _advance_interval(next_run_at: datetime, interval_seconds: int, now: datetime) -> datetime:
    advanced = next_run_at
    step = timedelta(seconds=interval_seconds)
    while advanced <= now:
        advanced += step
    return advanced


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
```

- [ ] **Step 4: Verify, review, and commit Task 3**

```bash
python -m pytest tests/integration/test_job_schedules_service.py tests/integration/test_job_schedules_repository.py -q
python -m py_compile src/quant_trading/jobs/schedules.py
rg -n "run_due_schedules|create_job_schedule|update_job_schedule|SUPPORTED_SCHEDULE_JOB_TYPES|_advance_interval|interval_seconds" src/quant_trading/jobs/schedules.py tests/integration/test_job_schedules_service.py docs/superpowers/specs/2026-06-23-quant-trading-scheduled-operations-design.md
```

Expected: tests and py_compile exit 0; grep shows service coverage. Spec review: only `market_data_sync` schedules are accepted; short intervals are rejected; `next_run_at` advances repeatedly until after `now`. Quality review: no backlog burst, no external scheduler package, no real Redis/AkShare dependency in tests.

Commit:

```bash
git add src/quant_trading/jobs/schedules.py tests/integration/test_job_schedules_service.py
git commit -m "feat: add scheduled job service"
```

## Task 4: APIs And Auth

**Files:**

- Create: `src/quant_trading/api/routes/schedules.py`
- Modify: `src/quant_trading/api/routes/jobs.py`
- Modify: `src/quant_trading/api/main.py`
- Create: `tests/integration/test_schedules_api.py`
- Modify: `tests/integration/test_jobs_api.py`
- Modify: `tests/integration/test_runtime_auth.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/integration/test_schedules_api.py`:

```python
from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine, AppSettings(job_executor="rq", redis_url="redis://fake:6379/0")))


def test_schedule_api_create_list_patch_and_get_missing():
    client = make_client()
    created = client.post("/job-schedules", json={"name": "daily-000001-sync", "job_type": "market_data_sync", "request_payload": {"provider": "akshare", "symbol": "000001"}, "interval_seconds": 86400, "next_run_at": "2026-06-23T09:30:00"})
    listed = client.get("/job-schedules")
    patched = client.patch(f"/job-schedules/{created.json()['id']}", json={"enabled": False})
    missing = client.get("/job-schedules/99")

    assert created.status_code == 200
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "daily-000001-sync"
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert missing.status_code == 404


def test_schedule_api_rejects_invalid_schedule():
    client = make_client()
    response = client.post("/job-schedules", json={"name": "bad", "job_type": "paper_run_tick", "request_payload": {}, "interval_seconds": 30, "next_run_at": "2026-06-23T09:30:00"})

    assert response.status_code == 400
```

Append to `tests/integration/test_jobs_api.py`:

```python
def test_job_cancel_api_cancels_queued_job_and_events_api_lists_timeline():
    from quant_trading.jobs.runtime import IMPORT_LEGACY, job_payload_dumps, utcnow
    from quant_trading.storage.db import session_scope
    from quant_trading.storage.repositories import JobEventRepository, JobRunRepository

    client, engine = make_client(AppSettings(job_executor="rq", redis_url="redis://fake:6379/0"))
    with session_scope(engine) as session:
        row = JobRunRepository(session).create_queued(IMPORT_LEGACY, job_payload_dumps({"legacy_db_path": "legacy.sqlite3"}), utcnow())
        JobEventRepository(session).record(row.id, "queued", "job queued", progress=0, created_at=utcnow())
        job_run_id = row.id

    cancel_response = client.post(f"/jobs/{job_run_id}/cancel")
    events_response = client.get(f"/jobs/{job_run_id}/events")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    assert events_response.status_code == 200
    assert [row["event_type"] for row in events_response.json()] == ["queued", "cancelled"]
```

- [ ] **Step 2: Verify tests fail**

```bash
python -m pytest tests/integration/test_schedules_api.py tests/integration/test_jobs_api.py::test_job_cancel_api_cancels_queued_job_and_events_api_lists_timeline -q
```

Expected: FAIL because schedules, cancel, and event routes do not exist.

- [ ] **Step 3: Implement schedules API**

Create `src/quant_trading/api/routes/schedules.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from quant_trading.jobs.queue import make_queue
from quant_trading.jobs.schedules import (
    create_job_schedule,
    run_due_schedules,
    update_job_schedule,
)
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobScheduleORM
from quant_trading.storage.repositories import JobScheduleRepository

router = APIRouter(prefix="/job-schedules", tags=["job-schedules"])


class ScheduleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    job_type: str
    request_payload: dict[str, Any] = Field(default_factory=dict)
    interval_seconds: int
    next_run_at: datetime
    enabled: bool = True


class ScheduleUpdateRequest(BaseModel):
    enabled: bool | None = None
    request_payload: dict[str, Any] | None = None
    interval_seconds: int | None = None
    next_run_at: datetime | None = None


class RunDueRequest(BaseModel):
    now: datetime | None = None


@router.post("")
def create_schedule(payload: ScheduleCreateRequest, request: Request) -> dict[str, Any]:
    try:
        row = create_job_schedule(
            request.app.state.engine,
            name=payload.name,
            job_type=payload.job_type,
            request_payload=payload.request_payload,
            interval_seconds=payload.interval_seconds,
            next_run_at=payload.next_run_at,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _schedule_payload(row)


@router.get("")
def list_schedules(
    request: Request,
    enabled: bool | None = None,
    job_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = JobScheduleRepository(session).list_recent(
            enabled=enabled,
            job_type=job_type,
            limit=limit,
        )
        return [_schedule_payload(row) for row in rows]


@router.post("/run-due")
def run_due(payload: RunDueRequest, request: Request) -> list[dict[str, Any]]:
    now = payload.now or datetime.now(UTC).replace(tzinfo=None)
    return run_due_schedules(
        request.app.state.engine,
        request.app.state.settings,
        now,
        make_queue,
    )


@router.get("/{schedule_id}")
def get_schedule(schedule_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = JobScheduleRepository(session).get(schedule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="job schedule not found")
        return _schedule_payload(row)


@router.patch("/{schedule_id}")
def patch_schedule(
    schedule_id: int,
    payload: ScheduleUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        row = update_job_schedule(
            request.app.state.engine,
            schedule_id,
            **payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("job schedule not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return _schedule_payload(row)


def _schedule_payload(row: JobScheduleORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "job_type": row.job_type,
        "request_payload": _json_loads(row.request_payload),
        "schedule_type": row.schedule_type,
        "interval_seconds": row.interval_seconds,
        "enabled": row.enabled,
        "next_run_at": _iso(row.next_run_at),
        "last_run_at": _iso(row.last_run_at),
        "last_job_run_id": row.last_job_run_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    loaded = json.loads(value or "{}")
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
```

Modify `src/quant_trading/api/main.py` to import `schedules` and call `app.include_router(schedules.router)`.

- [ ] **Step 4: Implement job cancel and events API**

Modify `src/quant_trading/api/routes/jobs.py`. Import `cancel_job_run`, `JobEventORM`, and `JobEventRepository`. Add these routes before `@router.get("/{job_run_id}")`:

```python
@router.post("/{job_run_id}/cancel")
def cancel_job(job_run_id: int, request: Request) -> dict[str, Any]:
    try:
        return _job_payload(cancel_job_run(request.app.state.engine, job_run_id))
    except ValueError as exc:
        message = str(exc)
        if message.startswith("job run not found"):
            raise HTTPException(status_code=404, detail=message) from exc
        if message.startswith("cannot cancel terminal job"):
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc


@router.get("/{job_run_id}/events")
def list_job_events(job_run_id: int, request: Request) -> list[dict[str, Any]]:
    with session_scope(request.app.state.engine) as session:
        if JobRunRepository(session).get(job_run_id) is None:
            raise HTTPException(status_code=404, detail="job run not found")
        return [_job_event_payload(row) for row in JobEventRepository(session).list_for_job(job_run_id)]


def _job_event_payload(row: JobEventORM) -> dict[str, Any]:
    return {"id": row.id, "job_run_id": row.job_run_id, "event_type": row.event_type, "message": row.message, "progress": row.progress, "payload": _json_loads(row.payload), "created_at": _iso(row.created_at)}
```

- [ ] **Step 5: Add auth coverage**

Append to `tests/integration/test_runtime_auth.py`:

```python
def test_schedule_api_requires_auth_when_enabled():
    client = make_client()

    response = client.get("/job-schedules")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_job_events_api_requires_auth_when_enabled():
    client = make_client()

    response = client.get("/jobs/1/events")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
```

- [ ] **Step 6: Verify, review, and commit Task 4**

```bash
python -m pytest tests/integration/test_schedules_api.py tests/integration/test_jobs_api.py tests/integration/test_runtime_auth.py -q
python -m py_compile src/quant_trading/api/routes/schedules.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/main.py
rg -n "/job-schedules|run-due|/cancel|/events|ScheduleCreateRequest|cancel_job|list_job_events" src/quant_trading/api tests/integration docs/superpowers/specs/2026-06-23-quant-trading-scheduled-operations-design.md
```

Expected: tests and py_compile exit 0; grep shows API coverage. Spec review: schedule CRUD, run-due, cancel, events, and auth coverage exist. Quality review: specific job subroutes appear before `/jobs/{job_run_id}`; route handlers delegate to services/repositories; request payloads are JSON objects.

Commit:

```bash
git add src/quant_trading/api/routes/schedules.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/main.py tests/integration/test_schedules_api.py tests/integration/test_jobs_api.py tests/integration/test_runtime_auth.py
git commit -m "feat: expose scheduled operations APIs"
```

## Task 5: Dashboard, README, And Final Verification

**Files:**

- Modify: `src/quant_trading/api/routes/dashboard.py`
- Modify: `tests/integration/test_dashboard.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing dashboard test**

Append to `tests/integration/test_dashboard.py`:

```python
def test_dashboard_displays_job_schedules_and_events():
    from datetime import UTC, datetime

    from quant_trading.jobs.runtime import MARKET_DATA_SYNC, job_payload_dumps
    from quant_trading.storage.db import session_scope
    from quant_trading.storage.repositories import JobEventRepository, JobRunRepository, JobScheduleRepository

    client, engine = make_client()
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        job = JobRunRepository(session).create_queued(MARKET_DATA_SYNC, job_payload_dumps({"provider": "fake", "symbol": "000001"}), now)
        JobEventRepository(session).record(job.id, "queued", "job queued", progress=0, created_at=now)
        JobScheduleRepository(session).create("daily-000001-sync", MARKET_DATA_SYNC, job_payload_dumps({"provider": "fake", "symbol": "000001"}), "interval", 86400, True, now, now)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Job Schedules" in response.text
    assert "daily-000001-sync" in response.text
    assert "Job Events" in response.text
    assert "job queued" in response.text
```

- [ ] **Step 2: Verify dashboard test fails**

```bash
python -m pytest tests/integration/test_dashboard.py::test_dashboard_displays_job_schedules_and_events -q
```

Expected: FAIL because dashboard does not render schedules or job events.

- [ ] **Step 3: Render schedules and events**

Modify `src/quant_trading/api/routes/dashboard.py`: import `JobEventRepository` and `JobScheduleRepository`; add `"job_schedules": JobScheduleRepository(session).list_recent(limit=20)` and `"job_events": JobEventRepository(session).list_recent(limit=30)` to `_collect_state()`; render `_job_schedules_table(state)` and `_job_events_table(state)` after `_job_runs_table(state)`.

Add:

```python
def _job_schedules_table(state: dict[str, Any]) -> str:
    return _table("Job Schedules", ["ID", "Name", "Type", "Enabled", "Interval", "Next Run", "Last Run", "Last Job"], state["job_schedules"], lambda r: [f"#{r.id}", r.name, r.job_type, "yes" if r.enabled else "no", f"{r.interval_seconds}s", r.next_run_at, r.last_run_at or "", f"#{r.last_job_run_id}" if r.last_job_run_id else ""])


def _job_events_table(state: dict[str, Any]) -> str:
    return _table("Job Events", ["ID", "Job", "Type", "Message", "Progress", "Created"], state["job_events"], lambda r: [f"#{r.id}", f"#{r.job_run_id}", r.event_type, r.message, f"{r.progress}%" if r.progress is not None else "", r.created_at])
```

- [ ] **Step 4: Update README**

Modify `README.md` with:

```markdown
### Scheduled operations and job control

Stage 7 adds an operator control plane around queued jobs:

- `POST /job-schedules` creates an enabled interval schedule for `market_data_sync`.
- `GET /job-schedules` lists configured schedules.
- `PATCH /job-schedules/{schedule_id}` enables, disables, or changes a schedule.
- `POST /job-schedules/run-due` runs one explicit scheduler tick.
- `POST /jobs/{job_run_id}/cancel` cancels queued jobs or requests cooperative cancellation for running jobs.
- `GET /jobs/{job_run_id}/events` returns the lifecycle timeline for a job.

The scheduler stores only job configuration and operational metadata. It does not store provider credentials, does not place real broker orders, and does not add live exchange execution.
```

- [ ] **Step 5: Verify, review, and commit Task 5**

Run focused checks:

```bash
python -m pytest tests/integration/test_job_events_repository.py tests/integration/test_job_schedules_repository.py tests/integration/test_job_events_runtime.py tests/integration/test_job_schedules_service.py tests/integration/test_schedules_api.py tests/integration/test_jobs_api.py tests/integration/test_runtime_auth.py tests/integration/test_dashboard.py tests/integration/test_migrations.py tests/integration/test_market_data_sync_service.py tests/integration/test_job_runtime.py -q
python -m py_compile src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py src/quant_trading/jobs/cancellation.py src/quant_trading/jobs/runtime.py src/quant_trading/jobs/service.py src/quant_trading/jobs/schedules.py src/quant_trading/data/sync.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/routes/schedules.py src/quant_trading/api/routes/dashboard.py src/quant_trading/api/main.py
docker compose config
git diff --check
```

Run full checks:

```bash
python -m pytest -q
docker compose config
git status --short --branch
```

Expected: all commands exit 0; full test output reports all tests passed.

Spec review:

```bash
rg -n "Job Schedules|Job Events|job_events|job_schedules|run_due_schedules|cancel_requested|cancelled|/job-schedules|/events|/cancel|does not place real broker orders" README.md src tests docs/superpowers/specs/2026-06-23-quant-trading-scheduled-operations-design.md
```

Required evidence: interval schedules for `market_data_sync`, explicit scheduler tick, no backlog burst, queued/running cancellation, queryable timelines, dashboard visibility, auth, and README broker non-goal.

Quality review:

```bash
git diff -- src/quant_trading tests README.md migrations
```

Confirm no real Redis, AkShare, broker, or exchange dependency is required by tests; no secrets, tokens, raw provider payloads, or tracebacks are persisted in new tables; API code stays thin; dashboard remains dense and operational; no high-availability scheduler dependency is introduced.

Commit:

```bash
git add src/quant_trading/api/routes/dashboard.py tests/integration/test_dashboard.py README.md
git commit -m "docs: document scheduled operations"
```

- [ ] **Step 6: Final local history check**

```bash
git log --oneline --decorate -12
git status --short --branch
```

Expected: Stage 7 implementation commits are present; worktree is clean except branch is ahead of remote.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-23-quant-trading-scheduled-operations.md`.

Two execution options:

1. Subagent-Driven (recommended) - dispatch one fresh worker per task, review between tasks, fast iteration.
2. Inline Execution - execute tasks in this session using `superpowers:executing-plans`, with checkpoint reviews.
