# Quant Trading Market Data Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-backed, auditable daily market-data sync path that runs through the existing queued job runtime.

**Architecture:** Add `data_sync_runs` as the market-data ingestion audit model, then build a provider registry and sync service that validates requests, upserts instruments and bars, and records lifecycle. Extend Stage 5 jobs with a `market_data_sync` job type, expose API read/write routes, and surface sync runs on the dashboard.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Alembic, Pydantic, Redis/RQ-compatible job runtime, pytest/TestClient, fake providers for deterministic tests.

---

## Baseline

Implementation worktree:

```bash
cd /private/tmp/quant-stage4-runtime
git status --short --branch
```

Expected: clean worktree on `codex/quant-stage4-runtime-tmp`.

Stage 6 spec:

```bash
docs/superpowers/specs/2026-06-23-quant-trading-market-data-sync-design.md
```

## File Structure

Create:

- `migrations/versions/20260623_0003_add_data_sync_runs.py`
  Alembic migration for `data_sync_runs`.
- `src/quant_trading/data/providers/registry.py`
  Provider registry and default AkShare registration.
- `src/quant_trading/data/sync.py`
  Market data sync service, request validation, sync lifecycle recording, and provider-backed bar upserts.
- `src/quant_trading/api/routes/data_sync.py`
  Read API for sync run history.
- `tests/integration/test_data_sync_runs_repository.py`
  Repository lifecycle tests.
- `tests/unit/test_provider_registry.py`
  Provider registry behavior tests.
- `tests/integration/test_market_data_sync_service.py`
  Sync service success, idempotency, validation, and provider failure tests.
- `tests/integration/test_data_sync_api.py`
  `/data-sync-runs` read endpoint tests.

Modify:

- `src/quant_trading/storage/models.py`
  Add `DataSyncRunORM`.
- `src/quant_trading/storage/repositories.py`
  Add `DataSyncRunRepository`.
- `tests/integration/test_migrations.py`
  Assert Alembic creates `data_sync_runs`.
- `src/quant_trading/jobs/runtime.py`
  Add `MARKET_DATA_SYNC` job type and dispatch to `sync_daily_market_data()`.
- `src/quant_trading/api/routes/jobs.py`
  Add `POST /jobs/market-data/sync` request model and route.
- `src/quant_trading/api/main.py`
  Include data sync read router.
- `src/quant_trading/api/routes/dashboard.py`
  Render recent data sync runs.
- `tests/integration/test_job_runtime.py`
  Add market-data sync job runtime coverage.
- `tests/integration/test_jobs_api.py`
  Add market-data sync job API coverage.
- `tests/integration/test_runtime_auth.py`
  Add auth coverage for data sync read API.
- `tests/integration/test_dashboard.py`
  Add dashboard rendering coverage.
- `README.md`
  Document market-data sync endpoint, audit table, and no-live-order boundary.

## Task 1: Data Sync Storage And Migration

**Files:**

- Modify: `src/quant_trading/storage/models.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `migrations/versions/20260623_0003_add_data_sync_runs.py`
- Modify: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_data_sync_runs_repository.py`

- [ ] **Step 1: Write failing repository lifecycle tests**

Create `tests/integration/test_data_sync_runs_repository.py`:

```python
from datetime import UTC, date, datetime

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import DataSyncRunORM
from quant_trading.storage.repositories import DataSyncRunRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_data_sync_run_repository_lifecycle_records_success():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)

    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        row = repo.create_running(
            provider="akshare",
            symbol="000001",
            market="a_stock",
            asset_type="stock",
            currency="CNY",
            exchange="SZSE",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            job_run_id=9,
            started_at=now,
        )
        repo.mark_succeeded(row, imported_bars=3, finished_at=now, duration_ms=12)

    with session_scope(engine) as session:
        row = session.get(DataSyncRunORM, 1)
        assert row is not None
        assert row.provider == "akshare"
        assert row.symbol == "000001"
        assert row.status == "succeeded"
        assert row.imported_bars == 3
        assert row.job_run_id == 9
        assert row.error_message is None
        assert row.finished_at is not None
        assert row.duration_ms == 12


def test_data_sync_run_repository_filters_recent_rows_and_records_failure():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)

    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        first = repo.create_running("akshare", "000001", "a_stock", "stock", "CNY", "SZSE", None, None, None, now)
        second = repo.create_running("akshare", "600000", "a_stock", "stock", "CNY", "SSE", None, None, None, now)
        repo.mark_failed(first, "provider unavailable", now, 4)
        repo.mark_succeeded(second, imported_bars=0, finished_at=now, duration_ms=5)

    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        failed = repo.list_recent(status="failed")
        symbol_rows = repo.list_recent(symbol="600000")
        provider_rows = repo.list_recent(provider="akshare", limit=1)

        assert [row.symbol for row in failed] == ["000001"]
        assert [row.status for row in symbol_rows] == ["succeeded"]
        assert [row.symbol for row in provider_rows] == ["600000"]
        assert repo.get(2).exchange == "SSE"
```

- [ ] **Step 2: Run repository tests to verify failure**

Run:

```bash
python -m pytest tests/integration/test_data_sync_runs_repository.py -q
```

Expected: FAIL because `DataSyncRunORM` and `DataSyncRunRepository` do not exist.

- [ ] **Step 3: Add `DataSyncRunORM`**

Modify `src/quant_trading/storage/models.py`.

Add after `JobRunORM`:

```python
class DataSyncRunORM(Base):
    __tablename__ = "data_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str] = mapped_column(String(32), default="a_stock")
    asset_type: Mapped[str] = mapped_column(String(32), default="stock")
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    exchange: Mapped[str] = mapped_column(String(32), default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    imported_bars: Mapped[int] = mapped_column(Integer, default=0)
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Add `DataSyncRunRepository`**

Modify `src/quant_trading/storage/repositories.py`.

Update import:

```python
from quant_trading.storage.models import (
    DataSyncRunORM,
    InstrumentORM,
    JobRunORM,
    MarketBarORM,
    WorkflowRunORM,
)
```

Append:

```python
class DataSyncRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_running(
        self,
        provider: str,
        symbol: str,
        market: str,
        asset_type: str,
        currency: str,
        exchange: str,
        start_date: date | None,
        end_date: date | None,
        job_run_id: int | None,
        started_at: datetime,
    ) -> DataSyncRunORM:
        row = DataSyncRunORM(
            provider=provider,
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            currency=currency,
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
            status="running",
            imported_bars=0,
            job_run_id=job_run_id,
            started_at=started_at,
            created_at=started_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_succeeded(
        self,
        row: DataSyncRunORM,
        imported_bars: int,
        finished_at: datetime,
        duration_ms: int,
    ) -> DataSyncRunORM:
        row.status = "succeeded"
        row.imported_bars = imported_bars
        row.error_message = None
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def mark_failed(
        self,
        row: DataSyncRunORM,
        error_message: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> DataSyncRunORM:
        row.status = "failed"
        row.error_message = error_message
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        provider: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[DataSyncRunORM]:
        statement = select(DataSyncRunORM).order_by(DataSyncRunORM.id.desc()).limit(limit)
        if provider:
            statement = statement.where(DataSyncRunORM.provider == provider)
        if symbol:
            statement = statement.where(DataSyncRunORM.symbol == symbol)
        if status:
            statement = statement.where(DataSyncRunORM.status == status)
        return list(self.session.scalars(statement).all())

    def get(self, sync_run_id: int) -> DataSyncRunORM | None:
        return self.session.get(DataSyncRunORM, sync_run_id)
```

- [ ] **Step 5: Verify repository tests pass**

Run:

```bash
python -m pytest tests/integration/test_data_sync_runs_repository.py -q
```

Expected: PASS.

- [ ] **Step 6: Add failing migration assertion**

Modify `tests/integration/test_migrations.py`:

```python
    assert "data_sync_runs" in tables
```

Add it near the existing `"job_runs"` assertion.

- [ ] **Step 7: Run migration test to verify failure**

Run:

```bash
python -m pytest tests/integration/test_migrations.py -q
```

Expected: FAIL because Alembic does not create `data_sync_runs`.

- [ ] **Step 8: Add Alembic revision**

Create `migrations/versions/20260623_0003_add_data_sync_runs.py`:

```python
"""add data sync runs

Revision ID: 20260623_0003
Revises: 20260623_0002
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0003"
down_revision = "20260623_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("imported_bars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("job_run_id", sa.Integer(), sa.ForeignKey("job_runs.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_data_sync_runs_provider", "data_sync_runs", ["provider"])
    op.create_index("ix_data_sync_runs_symbol", "data_sync_runs", ["symbol"])
    op.create_index("ix_data_sync_runs_status", "data_sync_runs", ["status"])
    op.create_index("ix_data_sync_runs_job_run_id", "data_sync_runs", ["job_run_id"])


def downgrade() -> None:
    op.drop_index("ix_data_sync_runs_job_run_id", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_status", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_symbol", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_provider", table_name="data_sync_runs")
    op.drop_table("data_sync_runs")
```

- [ ] **Step 9: Verify Task 1**

Run:

```bash
python -m pytest tests/integration/test_data_sync_runs_repository.py tests/integration/test_migrations.py -q
python -m py_compile src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260623_0003_add_data_sync_runs.py
```

Expected: all commands exit 0.

- [ ] **Step 10: Spec review for Task 1**

Check:

```bash
rg -n "DataSyncRunORM|DataSyncRunRepository|data_sync_runs|job_run_id|imported_bars" src tests migrations docs/superpowers/specs/2026-06-23-quant-trading-market-data-sync-design.md
```

Required evidence:

- `data_sync_runs` fields match the spec.
- Migration creates the table and indexes.
- Repository supports running, succeeded, failed, list filters, and get.

- [ ] **Step 11: Quality review for Task 1**

Inspect:

- Repository does not commit transactions itself.
- No provider credentials or raw provider payload fields are stored.
- Existing repositories remain backward compatible.

- [ ] **Step 12: Commit Task 1**

Run:

```bash
git add src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260623_0003_add_data_sync_runs.py tests/integration/test_data_sync_runs_repository.py tests/integration/test_migrations.py
git commit -m "feat: add data sync run storage"
```

## Task 2: Provider Registry And Sync Service

**Files:**

- Create: `src/quant_trading/data/providers/registry.py`
- Create: `src/quant_trading/data/sync.py`
- Create: `tests/unit/test_provider_registry.py`
- Create: `tests/integration/test_market_data_sync_service.py`

- [ ] **Step 1: Write failing provider registry tests**

Create `tests/unit/test_provider_registry.py`:

```python
import pytest

from quant_trading.data.providers.registry import (
    ProviderRegistry,
    build_default_provider_registry,
)


class FakeProvider:
    name = "fake"


def test_provider_registry_normalizes_names():
    registry = ProviderRegistry([FakeProvider()])

    assert registry.get(" FAKE ") is registry.get("fake")
    assert registry.names() == ["fake"]


def test_provider_registry_rejects_unknown_provider():
    registry = ProviderRegistry([FakeProvider()])

    with pytest.raises(ValueError, match="unknown market data provider: missing"):
        registry.get("missing")


def test_default_provider_registry_contains_akshare_without_importing_network_client():
    registry = build_default_provider_registry()

    assert "akshare" in registry.names()
```

- [ ] **Step 2: Verify provider registry tests fail**

Run:

```bash
python -m pytest tests/unit/test_provider_registry.py -q
```

Expected: FAIL because `quant_trading.data.providers.registry` does not exist.

- [ ] **Step 3: Implement provider registry**

Create `src/quant_trading/data/providers/registry.py`:

```python
from __future__ import annotations

from collections.abc import Iterable

from quant_trading.data.providers.akshare_provider import AkshareProvider
from quant_trading.data.providers.base import MarketDataProvider


class ProviderRegistry:
    def __init__(self, providers: Iterable[MarketDataProvider]):
        self._providers = {
            self._normalize(provider.name): provider
            for provider in providers
        }

    def get(self, name: str) -> MarketDataProvider:
        normalized = self._normalize(name)
        try:
            return self._providers[normalized]
        except KeyError as exc:
            raise ValueError(f"unknown market data provider: {normalized}") from exc

    def names(self) -> list[str]:
        return sorted(self._providers)

    def _normalize(self, name: str) -> str:
        normalized = str(name or "").strip().lower()
        if not normalized:
            raise ValueError("market data provider is required")
        return normalized


def build_default_provider_registry() -> ProviderRegistry:
    return ProviderRegistry([AkshareProvider()])
```

- [ ] **Step 4: Verify provider registry tests pass**

Run:

```bash
python -m pytest tests/unit/test_provider_registry.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing sync service tests**

Create `tests/integration/test_market_data_sync_service.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.data.providers.registry import ProviderRegistry
from quant_trading.data.sync import sync_daily_market_data
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import DataSyncRunORM
from quant_trading.storage.repositories import InstrumentRepository, MarketDataRepository


class FakeProvider:
    name = "fake"

    def __init__(self, bars=None, error: Exception | None = None):
        self.bars = bars or []
        self.error = error
        self.calls = []

    def fetch_daily_bars(self, instrument_id, symbol, start, end):
        self.calls.append((instrument_id, symbol, start, end))
        if self.error is not None:
            raise self.error
        return [
            Bar(
                instrument_id=instrument_id,
                symbol=symbol,
                market=Market.A_STOCK,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source=self.name,
            )
            for bar in self.bars
        ]


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def make_bar(timestamp: date | str) -> Bar:
    return Bar(
        instrument_id=0,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=timestamp,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("1000"),
        source="fake",
    )


def test_sync_daily_market_data_upserts_instrument_bars_and_audit_row():
    engine = make_engine_with_schema()
    provider = FakeProvider([make_bar("2026-01-01"), make_bar(date(2026, 1, 2))])
    registry = ProviderRegistry([provider])

    result = sync_daily_market_data(
        engine,
        provider_name="fake",
        symbol="000001",
        start="2026-01-01",
        end="2026-01-02",
        registry=registry,
        job_run_id=5,
    )
    second = sync_daily_market_data(
        engine,
        provider_name="fake",
        symbol="000001",
        start="2026-01-01",
        end="2026-01-02",
        registry=registry,
        job_run_id=6,
    )

    assert result["provider"] == "fake"
    assert result["symbol"] == "000001"
    assert result["imported_bars"] == 2
    assert result["sync_run_id"] == 1
    assert second["sync_run_id"] == 2
    assert provider.calls[0][1:] == ("000001", "2026-01-01", "2026-01-02")

    with session_scope(engine) as session:
        instrument = InstrumentRepository(session).get_by_symbol("000001")
        bars = MarketDataRepository(session).list_bars("000001")
        sync_run = session.get(DataSyncRunORM, 1)
        assert instrument is not None
        assert instrument.exchange == "SZSE"
        assert len(bars) == 2
        assert sync_run.status == "succeeded"
        assert sync_run.job_run_id == 5


def test_sync_daily_market_data_validates_before_provider_call():
    engine = make_engine_with_schema()
    provider = FakeProvider([make_bar(date(2026, 1, 1))])
    registry = ProviderRegistry([provider])

    with pytest.raises(ValueError, match="symbol is required"):
        sync_daily_market_data(engine, "fake", "   ", None, None, registry=registry)
    with pytest.raises(ValueError, match="start_date must be before or equal to end_date"):
        sync_daily_market_data(engine, "fake", "000001", "2026-02-01", "2026-01-01", registry=registry)
    with pytest.raises(ValueError, match="invalid date"):
        sync_daily_market_data(engine, "fake", "000001", "bad-date", None, registry=registry)

    assert provider.calls == []


def test_sync_daily_market_data_marks_failed_on_provider_error():
    engine = make_engine_with_schema()
    registry = ProviderRegistry([FakeProvider(error=RuntimeError("provider unavailable"))])

    with pytest.raises(RuntimeError, match="provider unavailable"):
        sync_daily_market_data(engine, "fake", "600000", None, None, registry=registry)

    with session_scope(engine) as session:
        sync_run = session.get(DataSyncRunORM, 1)
        assert sync_run.provider == "fake"
        assert sync_run.symbol == "600000"
        assert sync_run.exchange == "SSE"
        assert sync_run.status == "failed"
        assert sync_run.error_message == "provider unavailable"
```

- [ ] **Step 6: Verify sync service tests fail**

Run:

```bash
python -m pytest tests/integration/test_market_data_sync_service.py -q
```

Expected: FAIL because `quant_trading.data.sync` does not exist.

- [ ] **Step 7: Implement sync service**

Create `src/quant_trading/data/sync.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime
import time
from typing import Any

from sqlalchemy import Engine

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.data.providers.registry import ProviderRegistry, build_default_provider_registry
from quant_trading.data.validation import validate_bars
from quant_trading.storage.db import session_scope
from quant_trading.storage.repositories import (
    DataSyncRunRepository,
    InstrumentRepository,
    MarketDataRepository,
)


def sync_daily_market_data(
    engine: Engine,
    provider_name: str,
    symbol: str,
    start: str | date | None,
    end: str | date | None,
    *,
    registry: ProviderRegistry | None = None,
    job_run_id: int | None = None,
) -> dict[str, Any]:
    provider_name = _normalize_provider_name(provider_name)
    symbol = _normalize_symbol(symbol)
    start_date = _parse_date(start, "start")
    end_date = _parse_date(end, "end")
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    registry = registry or build_default_provider_registry()
    provider = registry.get(provider_name)
    exchange = _derive_exchange(symbol)
    market = Market.A_STOCK.value
    asset_type = "stock"
    currency = "CNY"
    started_at = _utcnow()
    started_counter = time.perf_counter()

    with session_scope(engine) as session:
        sync_repo = DataSyncRunRepository(session)
        sync_run = sync_repo.create_running(
            provider=provider_name,
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            currency=currency,
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
            job_run_id=job_run_id,
            started_at=started_at,
        )
        instrument = InstrumentRepository(session).upsert_symbol(
            symbol=symbol,
            name=symbol,
            market=Market.A_STOCK,
            asset_type=asset_type,
            currency=currency,
            exchange=exchange,
        )
        sync_run_id = sync_run.id
        instrument_id = instrument.id

    try:
        bars = validate_bars(
            [
                _normalize_bar(instrument_id, symbol, bar)
                for bar in provider.fetch_daily_bars(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    start=start_date.isoformat() if start_date else None,
                    end=end_date.isoformat() if end_date else None,
                )
            ]
        )
        with session_scope(engine) as session:
            bars_repo = MarketDataRepository(session)
            for bar in bars:
                bars_repo.upsert_daily_bar(
                    instrument_id=instrument_id,
                    timestamp=bar.timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    source=bar.source,
                    adjusted=bar.adjusted.value,
                )
            sync_repo = DataSyncRunRepository(session)
            sync_run = sync_repo.get(sync_run_id)
            if sync_run is not None:
                sync_repo.mark_succeeded(
                    sync_run,
                    imported_bars=len(bars),
                    finished_at=_utcnow(),
                    duration_ms=_duration_ms(started_counter),
                )
    except Exception as exc:
        with session_scope(engine) as session:
            sync_repo = DataSyncRunRepository(session)
            sync_run = sync_repo.get(sync_run_id)
            if sync_run is not None:
                sync_repo.mark_failed(
                    sync_run,
                    error_message=_sanitize_error(exc),
                    finished_at=_utcnow(),
                    duration_ms=_duration_ms(started_counter),
                )
        raise

    return {
        "sync_run_id": sync_run_id,
        "provider": provider_name,
        "symbol": symbol,
        "imported_bars": len(bars),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }


def _normalize_bar(instrument_id: int, symbol: str, bar: Bar) -> Bar:
    return Bar(
        instrument_id=instrument_id,
        symbol=symbol,
        market=Market.A_STOCK,
        timestamp=_bar_date(bar.timestamp),
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        amount=bar.amount,
        adjusted=bar.adjusted,
        source=bar.source,
    )


def _bar_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _normalize_provider_name(provider_name: str) -> str:
    normalized = str(provider_name or "").strip().lower()
    if not normalized:
        raise ValueError("market data provider is required")
    return normalized


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip()
    if not normalized:
        raise ValueError("symbol is required")
    if len(normalized) > 32:
        raise ValueError("symbol is too long")
    return normalized


def _parse_date(value: str | date | None, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid date for {field_name}: {value}") from exc


def _derive_exchange(symbol: str) -> str:
    code = symbol.zfill(6)
    if code.startswith(("600", "601", "603", "605", "688")):
        return "SSE"
    return "SZSE"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _duration_ms(started_counter: float) -> int:
    return max(0, int((time.perf_counter() - started_counter) * 1000))


def _sanitize_error(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__)[:1000]
```

- [ ] **Step 8: Verify Task 2**

Run:

```bash
python -m pytest tests/unit/test_provider_registry.py tests/integration/test_market_data_sync_service.py -q
python -m py_compile src/quant_trading/data/providers/registry.py src/quant_trading/data/sync.py
```

Expected: all commands exit 0.

- [ ] **Step 9: Spec review for Task 2**

Check:

```bash
rg -n "ProviderRegistry|build_default_provider_registry|sync_daily_market_data|data_sync_runs|provider unavailable|start_date" src tests docs/superpowers/specs/2026-06-23-quant-trading-market-data-sync-design.md
```

Required evidence:

- Registry normalizes names and supports fake providers.
- Sync service validates before provider calls.
- Sync service creates succeeded and failed audit rows.
- Bars are upserted idempotently through `MarketDataRepository`.

- [ ] **Step 10: Quality review for Task 2**

Inspect:

- AkShare import remains lazy.
- Sync service stores no credentials or raw provider payloads.
- Service uses existing repositories and transaction pattern.

- [ ] **Step 11: Commit Task 2**

Run:

```bash
git add src/quant_trading/data/providers/registry.py src/quant_trading/data/sync.py tests/unit/test_provider_registry.py tests/integration/test_market_data_sync_service.py
git commit -m "feat: sync market data from providers"
```

## Task 3: Job Runtime And API Routes

**Files:**

- Modify: `src/quant_trading/jobs/runtime.py`
- Modify: `src/quant_trading/api/routes/jobs.py`
- Create: `src/quant_trading/api/routes/data_sync.py`
- Modify: `src/quant_trading/api/main.py`
- Modify: `tests/integration/test_job_runtime.py`
- Modify: `tests/integration/test_jobs_api.py`
- Create: `tests/integration/test_data_sync_api.py`
- Modify: `tests/integration/test_runtime_auth.py`

- [ ] **Step 1: Add failing job runtime test**

Append to `tests/integration/test_job_runtime.py`:

```python
from datetime import date
from decimal import Decimal

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.jobs.runtime import MARKET_DATA_SYNC
```

Append:

```python
def test_execute_market_data_sync_job_records_success(monkeypatch):
    class FakeProvider:
        name = "fake"

        def fetch_daily_bars(self, instrument_id, symbol, start, end):
            return [
                Bar(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    market=Market.A_STOCK,
                    timestamp=date(2026, 1, 1),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10.5"),
                    volume=Decimal("1000"),
                    source=self.name,
                )
            ]

    from quant_trading.data.providers.registry import ProviderRegistry
    from quant_trading.jobs import runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "build_default_provider_registry",
        lambda: ProviderRegistry([FakeProvider()]),
    )
    engine = make_engine_with_schema()
    job_run_id = create_job(
        engine,
        MARKET_DATA_SYNC,
        {"provider": "fake", "symbol": "000001", "start": "2026-01-01", "end": "2026-01-02"},
    )

    result = execute_job_run_with_engine(engine, job_run_id)

    job = get_job(engine, job_run_id)
    assert result["status"] == "succeeded"
    assert job.status == "succeeded"
    assert job.workflow_run_id == 1
    assert json.loads(job.result_payload)["imported_bars"] == 1
```

- [ ] **Step 2: Verify job runtime test fails**

Run:

```bash
python -m pytest tests/integration/test_job_runtime.py::test_execute_market_data_sync_job_records_success -q
```

Expected: FAIL because `MARKET_DATA_SYNC` does not exist.

- [ ] **Step 3: Add runtime dispatch**

Modify `src/quant_trading/jobs/runtime.py`.

Add imports:

```python
from quant_trading.data.providers.registry import build_default_provider_registry
from quant_trading.data.sync import sync_daily_market_data
```

Add constant:

```python
MARKET_DATA_SYNC = "market_data_sync"
```

Add to `SUPPORTED_JOB_TYPES`:

```python
MARKET_DATA_SYNC
```

Add to `_execute_payload()` before final raise:

```python
    if job_type == MARKET_DATA_SYNC:
        return sync_daily_market_data(
            engine,
            provider_name=str(payload.get("provider", "akshare")),
            symbol=str(payload["symbol"]),
            start=payload.get("start"),
            end=payload.get("end"),
            registry=build_default_provider_registry(),
            job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
        )
```

Change `execute_job_run_with_engine()` after loading `request_payload`:

```python
        if job_type == MARKET_DATA_SYNC:
            request_payload = {**request_payload, "job_run_id": job_run_id}
```

- [ ] **Step 4: Verify job runtime tests pass**

Run:

```bash
python -m pytest tests/integration/test_job_runtime.py tests/integration/test_market_data_sync_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Add failing jobs API test**

Append to `tests/integration/test_jobs_api.py`:

```python
def test_inline_market_data_sync_job_api_returns_succeeded_job(monkeypatch):
    from datetime import date
    from decimal import Decimal

    from quant_trading.core.enums import Market
    from quant_trading.core.models import Bar
    from quant_trading.data.providers.registry import ProviderRegistry
    from quant_trading.jobs import runtime as runtime_module

    class FakeProvider:
        name = "fake"

        def fetch_daily_bars(self, instrument_id, symbol, start, end):
            return [
                Bar(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    market=Market.A_STOCK,
                    timestamp=date(2026, 1, 1),
                    open=Decimal("10"),
                    high=Decimal("11"),
                    low=Decimal("9"),
                    close=Decimal("10.5"),
                    volume=Decimal("1000"),
                    source=self.name,
                )
            ]

    monkeypatch.setattr(
        runtime_module,
        "build_default_provider_registry",
        lambda: ProviderRegistry([FakeProvider()]),
    )
    client, _ = make_client()

    response = client.post(
        "/jobs/market-data/sync",
        json={"provider": "fake", "symbol": "000001", "start": "2026-01-01", "end": "2026-01-02"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "market_data_sync"
    assert payload["status"] == "succeeded"
    assert payload["result_payload"]["imported_bars"] == 1
```

- [ ] **Step 6: Verify jobs API test fails**

Run:

```bash
python -m pytest tests/integration/test_jobs_api.py::test_inline_market_data_sync_job_api_returns_succeeded_job -q
```

Expected: FAIL because `/jobs/market-data/sync` does not exist.

- [ ] **Step 7: Add market-data sync job route**

Modify `src/quant_trading/api/routes/jobs.py`.

Add imports:

```python
from pydantic import BaseModel, Field
from quant_trading.jobs.runtime import MARKET_DATA_SYNC
```

Add request model after router:

```python
class MarketDataSyncRequest(BaseModel):
    provider: str = "akshare"
    symbol: str = Field(min_length=1)
    start: str | None = None
    end: str | None = None
```

Add route:

```python
@router.post("/market-data/sync")
def create_market_data_sync_job(payload: MarketDataSyncRequest, request: Request) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            MARKET_DATA_SYNC,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )
```

- [ ] **Step 8: Add failing data sync read API tests**

Create `tests/integration/test_data_sync_api.py`:

```python
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import DataSyncRunRepository


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine=engine)), engine


def seed_sync_run(engine):
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        row = repo.create_running("akshare", "000001", "a_stock", "stock", "CNY", "SZSE", None, None, 1, now)
        repo.mark_succeeded(row, imported_bars=10, finished_at=now, duration_ms=20)
        return row.id


def test_data_sync_read_apis_filter_and_get_runs():
    client, engine = make_client()
    sync_run_id = seed_sync_run(engine)

    list_response = client.get("/data-sync-runs", params={"provider": "akshare", "symbol": "000001"})
    get_response = client.get(f"/data-sync-runs/{sync_run_id}")
    missing_response = client.get("/data-sync-runs/999")

    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [sync_run_id]
    assert get_response.status_code == 200
    assert get_response.json()["imported_bars"] == 10
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "data sync run not found"}
```

- [ ] **Step 9: Verify read API tests fail**

Run:

```bash
python -m pytest tests/integration/test_data_sync_api.py -q
```

Expected: FAIL because `/data-sync-runs` routes do not exist.

- [ ] **Step 10: Implement data sync read API**

Create `src/quant_trading/api/routes/data_sync.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import DataSyncRunORM
from quant_trading.storage.repositories import DataSyncRunRepository

router = APIRouter(prefix="/data-sync-runs", tags=["data-sync"])


@router.get("")
def list_data_sync_runs(
    request: Request,
    provider: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = DataSyncRunRepository(session).list_recent(
            provider=provider,
            symbol=symbol,
            status=status,
            limit=limit,
        )
        return [_data_sync_run_payload(row) for row in rows]


@router.get("/{sync_run_id}")
def get_data_sync_run(sync_run_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = DataSyncRunRepository(session).get(sync_run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="data sync run not found")
        return _data_sync_run_payload(row)


def _data_sync_run_payload(row: DataSyncRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "symbol": row.symbol,
        "market": row.market,
        "asset_type": row.asset_type,
        "currency": row.currency,
        "exchange": row.exchange,
        "start_date": _iso(row.start_date),
        "end_date": _iso(row.end_date),
        "status": row.status,
        "imported_bars": row.imported_bars,
        "job_run_id": row.job_run_id,
        "error_message": row.error_message,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
        "created_at": _iso(row.created_at),
    }


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
```

Modify `src/quant_trading/api/main.py` import:

```python
from quant_trading.api.routes import dashboard, backtests, data_sync, health, instruments, jobs, paper, workflows
```

Add before dashboard router:

```python
    app.include_router(data_sync.router)
```

- [ ] **Step 11: Add auth regression**

Append to `tests/integration/test_runtime_auth.py`:

```python
def test_data_sync_api_requires_auth_when_enabled():
    client = make_client()

    response = client.get("/data-sync-runs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
```

- [ ] **Step 12: Verify Task 3**

Run:

```bash
python -m pytest tests/integration/test_job_runtime.py tests/integration/test_jobs_api.py tests/integration/test_data_sync_api.py tests/integration/test_runtime_auth.py -q
python -m py_compile src/quant_trading/jobs/runtime.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/routes/data_sync.py src/quant_trading/api/main.py
```

Expected: all commands exit 0.

- [ ] **Step 13: Spec review for Task 3**

Check:

```bash
rg -n "market_data_sync|/jobs/market-data/sync|/data-sync-runs|MARKET_DATA_SYNC|DataSyncRunRepository|build_default_provider_registry" src tests docs/superpowers/specs/2026-06-23-quant-trading-market-data-sync-design.md
```

Required evidence:

- Job runtime supports `market_data_sync`.
- API exposes job creation and read routes.
- New routes are protected by existing middleware.
- Job result links to sync run and imported bar count.

- [ ] **Step 14: Quality review for Task 3**

Inspect:

- API route handlers stay thin.
- RQ mode still passes only database URL and job id.
- Fake provider testing does not require network access.
- Existing workflow routes remain backward compatible.

- [ ] **Step 15: Commit Task 3**

Run:

```bash
git add src/quant_trading/jobs/runtime.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/routes/data_sync.py src/quant_trading/api/main.py tests/integration/test_job_runtime.py tests/integration/test_jobs_api.py tests/integration/test_data_sync_api.py tests/integration/test_runtime_auth.py
git commit -m "feat: expose market data sync jobs"
```

## Task 4: Dashboard, README, And Final Verification

**Files:**

- Modify: `src/quant_trading/api/routes/dashboard.py`
- Modify: `tests/integration/test_dashboard.py`
- Modify: `README.md`

- [ ] **Step 1: Add failing dashboard test**

Append to `tests/integration/test_dashboard.py`:

```python
def test_dashboard_displays_data_sync_runs():
    from datetime import UTC, datetime

    from quant_trading.storage.repositories import DataSyncRunRepository

    client, engine = make_client()
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        row = repo.create_running("akshare", "000001", "a_stock", "stock", "CNY", "SZSE", None, None, 1, now)
        repo.mark_succeeded(row, imported_bars=10, finished_at=now, duration_ms=20)

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Data Sync Runs" in html
    assert "akshare" in html
    assert "000001" in html
    assert "10" in html
    assert "succeeded" in html
```

- [ ] **Step 2: Verify dashboard test fails**

Run:

```bash
python -m pytest tests/integration/test_dashboard.py::test_dashboard_displays_data_sync_runs -q
```

Expected: FAIL because dashboard does not render data sync runs.

- [ ] **Step 3: Render data sync runs in dashboard**

Modify `src/quant_trading/api/routes/dashboard.py`.

Update model imports:

```python
    DataSyncRunORM,
```

Update repository imports:

```python
from quant_trading.storage.repositories import (
    DataSyncRunRepository,
    JobRunRepository,
    WorkflowRunRepository,
)
```

In `_collect_state()`, add:

```python
            "data_sync_runs": DataSyncRunRepository(session).list_recent(limit=20),
```

In `_render_dashboard()`, render after job runs:

```python
  {_job_runs_table(state)}
  {_data_sync_runs_table(state)}
```

Add:

```python
def _data_sync_runs_table(state: dict[str, Any]) -> str:
    return _table(
        "Data Sync Runs",
        ["ID", "Provider", "Symbol", "Status", "Bars", "Range", "Job", "Duration", "Error"],
        state["data_sync_runs"],
        lambda r: [
            f"#{r.id}",
            r.provider,
            r.symbol,
            r.status,
            r.imported_bars,
            _date_range(r),
            f"#{r.job_run_id}" if r.job_run_id else "",
            f"{r.duration_ms} ms" if r.duration_ms is not None else "",
            r.error_message or "",
        ],
    )


def _date_range(row: DataSyncRunORM) -> str:
    if row.start_date and row.end_date:
        return f"{row.start_date} to {row.end_date}"
    if row.start_date:
        return f"from {row.start_date}"
    if row.end_date:
        return f"through {row.end_date}"
    return ""
```

- [ ] **Step 4: Verify dashboard tests pass**

Run:

```bash
python -m pytest tests/integration/test_dashboard.py tests/integration/test_data_sync_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Update README**

Modify `README.md`.

Add endpoint list entries:

```text
http://localhost:8000/jobs/market-data/sync
http://localhost:8000/data-sync-runs
http://localhost:8000/data-sync-runs/{sync_run_id}
```

Add section after `Queued Job Runtime`:

```markdown
## Market Data Sync

Stage 6 adds provider-backed daily market-data sync with audit rows in `data_sync_runs`.

Create a sync job:

```bash
curl -X POST http://127.0.0.1:8000/jobs/market-data/sync \
  -H "Content-Type: application/json" \
  -d '{"provider":"akshare","symbol":"000001","start":"2026-01-01","end":"2026-06-23"}'
```

Inspect sync history:

```bash
curl http://127.0.0.1:8000/data-sync-runs
curl http://127.0.0.1:8000/data-sync-runs/1
```

The sync path stores normalized daily bars idempotently and records provider, symbol, range, status, imported bar count, linked job id, and capped error text. Tests use fake providers; real local AkShare sync requires installing the optional `.[data]` dependencies. This still does not place broker or exchange orders.
```

Also update the roadmap by replacing the generic data-sync gap with the next remaining productization needs:

```markdown
- Add scheduled sync, cancellation, and live progress streaming for queued work.
```

- [ ] **Step 6: Focused Stage 6 verification**

Run:

```bash
python -m pytest tests/unit/test_provider_registry.py tests/integration/test_data_sync_runs_repository.py tests/integration/test_market_data_sync_service.py tests/integration/test_job_runtime.py tests/integration/test_jobs_api.py tests/integration/test_data_sync_api.py tests/integration/test_dashboard.py tests/integration/test_runtime_auth.py tests/integration/test_migrations.py -q
python -m py_compile src/quant_trading/data/providers/registry.py src/quant_trading/data/sync.py src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py src/quant_trading/jobs/runtime.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/routes/data_sync.py src/quant_trading/api/routes/dashboard.py src/quant_trading/api/main.py
docker compose config
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 7: Full verification**

Run:

```bash
python -m pytest -q
docker compose config
git status --short --branch
```

Expected:

- Pytest exits 0.
- Docker Compose config exits 0.
- Worktree only contains intended Task 4 changes before commit, then clean after commit.

- [ ] **Step 8: Spec review for Task 4 and full Stage 6**

Review `docs/superpowers/specs/2026-06-23-quant-trading-market-data-sync-design.md` against implementation evidence:

- Provider registry exists and registers AkShare.
- Sync service validates, syncs, upserts bars, and records audit rows.
- `data_sync_runs` exists in ORM and migration.
- `market_data_sync` job type exists.
- `/jobs/market-data/sync`, `/data-sync-runs`, and `/data-sync-runs/{id}` exist.
- Dashboard shows recent sync runs.
- No live broker/exchange order path was added.

- [ ] **Step 9: Quality review for Task 4 and full Stage 6**

Inspect:

- No tests rely on real AkShare network calls.
- Sync service does not store credentials or raw provider responses.
- API route handlers remain thin.
- Existing Stage 5 job behavior remains backward compatible.
- New docs keep safety boundary explicit.

- [ ] **Step 10: Commit Task 4**

Run:

```bash
git add README.md src/quant_trading/api/routes/dashboard.py tests/integration/test_dashboard.py
git commit -m "docs: document market data sync"
```

## Final Stage 6 Completion

After all four task commits:

```bash
python -m pytest -q
docker compose config
git log --oneline --decorate -10
git status --short --branch
```

Expected:

- Test suite exits 0.
- Compose config exits 0.
- Recent log contains the Stage 6 spec, plan, and four implementation commits.
- Worktree is clean.

Then use `superpowers:verification-before-completion` before making any completion claim, and follow AGENTS.md with a final Spec review and Quality review summary.
