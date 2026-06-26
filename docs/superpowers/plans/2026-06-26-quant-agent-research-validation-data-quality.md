# Quant Agent Research Validation Data Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic data quality reports, research validation reports, and validation-gated backtest review for Quant Agent candidates.

**Architecture:** Add two persisted report models and repositories, then layer deterministic services above the existing market-data, backtest, job, and agent audit paths. Data quality runs first, research validation consumes that evidence and historical MA Cross backtests, then `backtest_review` consumes persisted report summaries and caps readiness by the deterministic validation floor.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, pytest, existing inline/RQ job runtime, existing MA Cross strategy and simulated backtest engine.

---

## Branch And Scope Notes

- Working directory: `/Users/haobowang/Desktop/Code file/Python/LLM-Study/quant-trading/.worktrees/quant-agent-v1`
- Working branch: `codex/quant-agent-v3-approval-review-loop`
- Design spec: `docs/superpowers/specs/2026-06-26-quant-agent-research-validation-data-quality-design.md`
- This plan does not add UI dashboard work, paper-trading promotion, paper-run creation, broker calls, arbitrary strategy templates, or generated-code execution.
- Existing v3 behavior remains available only through an explicit `require_validation_report=false` override on backtest review requests.

## File Structure

- Modify: `src/quant_trading/storage/models.py`
  - Add `DataQualityReportORM` and `ResearchValidationReportORM`.
  - Add `data_quality_report_id` and `research_validation_report_id` to `AgentCandidateReviewORM`.
- Modify: `src/quant_trading/storage/repositories.py`
  - Add `DataQualityReportRepository` and `ResearchValidationReportRepository`.
  - Extend `AgentCandidateReviewRepository` with report-link helpers.
  - Extend `MarketDataRepository.list_bars()` with optional `start`, `end`, `source`, and `adjusted` filters.
- Create: `migrations/versions/20260626_0009_add_validation_reports.py`
  - Add report tables, indexes, unique candidate validation constraint, and candidate report links.
- Modify: `tests/integration/test_migrations.py`
  - Assert report tables, indexes, and candidate link columns.
- Create: `tests/integration/test_data_quality_reports_repository.py`
  - Repository lifecycle and filters.
- Create: `tests/integration/test_research_validation_reports_repository.py`
  - Repository lifecycle, update-in-place behavior, and candidate links.
- Create: `src/quant_trading/data/quality.py`
  - Deterministic data quality assessment and persisted report creation.
- Create: `tests/unit/test_data_quality.py`
  - Unit coverage for data-quality rules and fingerprinting.
- Create: `src/quant_trading/validation/__init__.py`
  - Package marker.
- Create: `src/quant_trading/validation/metrics.py`
  - Historical backtest metrics, readiness cap helper, and buy-and-hold benchmark metrics.
- Create: `tests/unit/test_research_validation_metrics.py`
  - Unit coverage for metrics and readiness capping.
- Modify: `src/quant_trading/backtest/engine.py`
  - Add optional date bounds to `BacktestEngine.run()`.
- Create: `src/quant_trading/validation/research.py`
  - Candidate research validation orchestration.
- Modify: `src/quant_trading/jobs/runtime.py`
  - Add `DATA_QUALITY_REPORT` and `RESEARCH_VALIDATION` job types.
- Modify: `src/quant_trading/api/routes/jobs.py`
  - Add job request models and endpoints.
- Create: `src/quant_trading/api/routes/data_quality_reports.py`
  - Read API for data quality reports.
- Create: `src/quant_trading/api/routes/research_validation_reports.py`
  - Read API for research validation reports.
- Modify: `src/quant_trading/api/main.py`
  - Register new routers.
- Modify: `src/quant_trading/api/routes/agent_candidates.py`
  - Include report IDs in candidate review payloads.
- Modify: `src/quant_trading/agents/models.py`
  - Add `require_validation_report` to `BacktestReviewRequest`.
- Modify: `src/quant_trading/agents/backtest_review.py`
  - Load report summaries and include them in prompt context.
- Modify: `src/quant_trading/agents/service.py`
  - Enforce validation report presence and cap readiness.
- Create: `tests/integration/test_validation_jobs.py`
  - Job/API/service integration coverage for report jobs.
- Modify: `tests/unit/test_backtest_review_agent.py`
  - Extend prompt context and readiness cap coverage.
- Modify: `tests/integration/test_agents_jobs.py`
  - Extend review gating and safety side-effect tests.
- Modify: `README.md`
  - Document the validation/data-quality loop and APIs.

## Review Protocol For Every Implementation Task

Each task must finish with both checks before commit:

1. **Spec review:** Compare the task against `docs/superpowers/specs/2026-06-26-quant-agent-research-validation-data-quality-design.md`. Confirm every acceptance criterion touched by the task is covered and no non-goal behavior slipped in.
2. **Quality review:** Check naming, JSON payload decoding, migration reversibility, date handling, divide-by-zero guards, API error mapping, secrets handling, and paper/broker isolation.

Record the review result in the task notes before committing. If either review fails, fix it before the next task.

---

### Task 1: Report Storage, Migration, And Repositories

**Files:**
- Modify: `src/quant_trading/storage/models.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `migrations/versions/20260626_0009_add_validation_reports.py`
- Modify: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_data_quality_reports_repository.py`
- Create: `tests/integration/test_research_validation_reports_repository.py`

- [ ] **Step 1: Write failing migration assertions**

Modify `tests/integration/test_migrations.py` to assert these new tables:

```python
assert "data_quality_reports" in tables
assert "research_validation_reports" in tables
```

Add column assertions:

```python
data_quality_columns = {
    column["name"] for column in inspector.get_columns("data_quality_reports")
}
assert {
    "id",
    "candidate_review_id",
    "backtest_run_id",
    "job_run_id",
    "symbol",
    "source",
    "adjusted",
    "start_date",
    "end_date",
    "bar_count",
    "expected_bar_count",
    "missing_bar_count",
    "duplicate_timestamp_count",
    "non_positive_price_count",
    "non_positive_volume_count",
    "invalid_ohlc_count",
    "stale_data",
    "data_fingerprint",
    "status",
    "severity",
    "findings_payload",
    "created_at",
    "finished_at",
    "duration_ms",
} <= data_quality_columns

validation_columns = {
    column["name"] for column in inspector.get_columns("research_validation_reports")
}
assert {
    "id",
    "candidate_review_id",
    "source_backtest_run_id",
    "data_quality_report_id",
    "job_run_id",
    "symbol",
    "strategy_name",
    "validation_status",
    "readiness_floor",
    "in_sample_metrics_payload",
    "out_of_sample_metrics_payload",
    "walk_forward_payload",
    "parameter_sensitivity_payload",
    "benchmark_payload",
    "summary_payload",
    "error_message",
    "created_at",
    "finished_at",
    "duration_ms",
} <= validation_columns

candidate_review_columns = {
    column["name"] for column in inspector.get_columns("agent_candidate_reviews")
}
assert {
    "data_quality_report_id",
    "research_validation_report_id",
} <= candidate_review_columns
```

- [ ] **Step 2: Write failing repository tests**

Create `tests/integration/test_data_quality_reports_repository.py` with tests for:

```python
def test_data_quality_report_repository_lifecycle_and_filters():
    # Create an in-memory database, create a running report, mark it completed,
    # then assert get/list filters return that row.
    # Use findings_payload='{"findings":[],"range":{"start":"2026-01-01","end":"2026-12-31"}}'.
    pass

def test_data_quality_report_repository_marks_failed_with_capped_error():
    # Create a running report, mark it failed with a 1200-character error string,
    # then assert status='failed', duration_ms is set, and len(error_message) == 1000.
    pass
```

Required assertions:

```python
assert row.status == "passed"
assert row.severity == "none"
assert row.symbol == "000001"
assert row.bar_count == 260
assert row.data_fingerprint == "a" * 64
assert repo.get(row.id).id == row.id
assert [item.id for item in repo.list_recent(symbol="000001")] == [row.id]
assert [item.id for item in repo.list_recent(status="passed")] == [row.id]
assert [item.id for item in repo.list_recent(severity="none")] == [row.id]
```

Create `tests/integration/test_research_validation_reports_repository.py` with tests for:

```python
def test_research_validation_report_repository_create_update_and_filters():
    # Seed candidate_review and source_backtest_run rows, create a running validation report,
    # mark it completed, then assert get/list filters and decoded payload columns are populated.
    pass

def test_research_validation_report_repository_reuses_candidate_row():
    # Create a validation report for candidate_review_id=1, call create_or_reset_running()
    # for candidate_review_id=1 again, and assert the same row id is reused.
    pass
```

Required assertions:

```python
assert row.validation_status == "passed"
assert row.readiness_floor == "ready_for_paper_research"
assert repo.get_by_candidate_review_id(candidate_review_id).id == row.id
assert [item.id for item in repo.list_recent(candidate_review_id=candidate_review_id)] == [row.id]
assert [item.id for item in repo.list_recent(validation_status="passed")] == [row.id]
assert updated.id == row.id
assert session.scalar(select(func.count(ResearchValidationReportORM.id))) == 1
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/integration/test_migrations.py \
  tests/integration/test_data_quality_reports_repository.py \
  tests/integration/test_research_validation_reports_repository.py \
  -q
```

Expected: FAIL because report ORM classes, repositories, and migration do not exist.

- [ ] **Step 4: Add ORM models and candidate links**

In `src/quant_trading/storage/models.py`, add imports already available in the file if needed and define:

```python
class DataQualityReportORM(Base):
    __tablename__ = "data_quality_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_candidate_reviews.id"), nullable=True, index=True
    )
    backtest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("backtest_runs.id"), nullable=True, index=True
    )
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64), default="")
    adjusted: Mapped[str] = mapped_column(String(16), default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bar_count: Mapped[int] = mapped_column(Integer, default=0)
    expected_bar_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_bar_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_timestamp_count: Mapped[int] = mapped_column(Integer, default=0)
    non_positive_price_count: Mapped[int] = mapped_column(Integer, default=0)
    non_positive_volume_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_ohlc_count: Mapped[int] = mapped_column(Integer, default=0)
    stale_data: Mapped[bool] = mapped_column(Boolean, default=False)
    data_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    severity: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    findings_payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ResearchValidationReportORM(Base):
    __tablename__ = "research_validation_reports"
    __table_args__ = (
        UniqueConstraint(
            "candidate_review_id",
            name="uq_research_validation_reports_candidate_review_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_review_id: Mapped[int] = mapped_column(
        ForeignKey("agent_candidate_reviews.id"), index=True
    )
    source_backtest_run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id"), index=True
    )
    data_quality_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_quality_reports.id"), nullable=True, index=True
    )
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), index=True)
    validation_status: Mapped[str] = mapped_column(
        String(32), default="running", index=True
    )
    readiness_floor: Mapped[str] = mapped_column(String(32), default="not_ready")
    in_sample_metrics_payload: Mapped[str] = mapped_column(Text, default="{}")
    out_of_sample_metrics_payload: Mapped[str] = mapped_column(Text, default="{}")
    walk_forward_payload: Mapped[str] = mapped_column(Text, default="{}")
    parameter_sensitivity_payload: Mapped[str] = mapped_column(Text, default="{}")
    benchmark_payload: Mapped[str] = mapped_column(Text, default="{}")
    summary_payload: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Extend `AgentCandidateReviewORM`:

```python
data_quality_report_id: Mapped[int | None] = mapped_column(
    ForeignKey("data_quality_reports.id"), nullable=True, index=True
)
research_validation_report_id: Mapped[int | None] = mapped_column(
    ForeignKey("research_validation_reports.id"), nullable=True, index=True
)
```

- [ ] **Step 5: Add Alembic migration**

Create `migrations/versions/20260626_0009_add_validation_reports.py` with:

```python
"""add validation reports

Revision ID: 20260626_0009
Revises: 20260624_0008
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260626_0009"
down_revision = "20260624_0008"
branch_labels = None
depends_on = None
```

Implement `upgrade()` to create both tables and all indexes. Add candidate columns with:

```python
with op.batch_alter_table("agent_candidate_reviews") as batch_op:
    batch_op.add_column(
        sa.Column(
            "data_quality_report_id",
            sa.Integer(),
            sa.ForeignKey("data_quality_reports.id"),
            nullable=True,
        )
    )
    batch_op.add_column(
        sa.Column(
            "research_validation_report_id",
            sa.Integer(),
            sa.ForeignKey("research_validation_reports.id"),
            nullable=True,
        )
    )
    batch_op.create_index(
        "ix_agent_candidate_reviews_data_quality_report_id",
        ["data_quality_report_id"],
    )
    batch_op.create_index(
        "ix_agent_candidate_reviews_research_validation_report_id",
        ["research_validation_report_id"],
    )
```

Implement `downgrade()` in reverse order and use `batch_alter_table()` to drop the two candidate columns.

- [ ] **Step 6: Add report repositories**

In `src/quant_trading/storage/repositories.py`, import the new ORM classes and add:

```python
class DataQualityReportRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_running(
        self,
        *,
        candidate_review_id: int | None,
        backtest_run_id: int | None,
        job_run_id: int | None,
        symbol: str,
        source: str,
        adjusted: str,
        start_date: date | None,
        end_date: date | None,
        created_at: datetime,
    ) -> DataQualityReportORM:
        pass

    def mark_completed(
        self,
        row: DataQualityReportORM,
        *,
        status: str,
        severity: str,
        bar_count: int,
        expected_bar_count: int,
        missing_bar_count: int,
        duplicate_timestamp_count: int,
        non_positive_price_count: int,
        non_positive_volume_count: int,
        invalid_ohlc_count: int,
        stale_data: bool,
        data_fingerprint: str,
        findings_payload: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> DataQualityReportORM:
        pass

    def mark_failed(
        self,
        row: DataQualityReportORM,
        *,
        error_message: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> DataQualityReportORM:
        pass

    def get(self, report_id: int) -> DataQualityReportORM | None:
        pass

    def list_recent(
        self,
        *,
        symbol: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        candidate_review_id: int | None = None,
        limit: int = 50,
    ) -> list[DataQualityReportORM]:
        pass
```

Add:

```python
class ResearchValidationReportRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_or_reset_running(
        self,
        *,
        candidate_review_id: int,
        source_backtest_run_id: int,
        data_quality_report_id: int | None,
        job_run_id: int | None,
        symbol: str,
        strategy_name: str,
        started_at: datetime,
    ) -> ResearchValidationReportORM:
        pass

    def mark_completed(
        self,
        row: ResearchValidationReportORM,
        *,
        validation_status: str,
        readiness_floor: str,
        in_sample_metrics_payload: str,
        out_of_sample_metrics_payload: str,
        walk_forward_payload: str,
        parameter_sensitivity_payload: str,
        benchmark_payload: str,
        summary_payload: str,
        data_quality_report_id: int | None,
        finished_at: datetime,
        duration_ms: int,
    ) -> ResearchValidationReportORM:
        pass

    def mark_failed(
        self,
        row: ResearchValidationReportORM,
        *,
        error_message: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> ResearchValidationReportORM:
        pass

    def get(self, report_id: int) -> ResearchValidationReportORM | None:
        pass

    def get_by_candidate_review_id(
        self, candidate_review_id: int
    ) -> ResearchValidationReportORM | None:
        pass

    def list_recent(
        self,
        *,
        candidate_review_id: int | None = None,
        symbol: str | None = None,
        validation_status: str | None = None,
        limit: int = 50,
    ) -> list[ResearchValidationReportORM]:
        pass
```

Add candidate review link helpers:

```python
def link_data_quality_report(
    self,
    row: AgentCandidateReviewORM,
    *,
    data_quality_report_id: int,
    updated_at: datetime,
) -> AgentCandidateReviewORM:
    row.data_quality_report_id = data_quality_report_id
    row.updated_at = updated_at
    self.session.flush()
    return row


def link_research_validation_report(
    self,
    row: AgentCandidateReviewORM,
    *,
    research_validation_report_id: int,
    updated_at: datetime,
) -> AgentCandidateReviewORM:
    row.research_validation_report_id = research_validation_report_id
    row.updated_at = updated_at
    self.session.flush()
    return row
```

- [ ] **Step 7: Run storage tests**

Run:

```bash
pytest tests/integration/test_migrations.py \
  tests/integration/test_data_quality_reports_repository.py \
  tests/integration/test_research_validation_reports_repository.py \
  tests/integration/test_agent_candidate_reviews_repository.py \
  -q
```

Expected: PASS.

- [ ] **Step 8: Run task review and commit**

Spec review checklist:

```text
Task 1 covers Data Model, Candidate Review Links, Migration, and repository acceptance criteria.
No API, job runtime, LLM, paper, or broker behavior was added.
```

Quality review checklist:

```text
Migration upgrades and downgrades on SQLite.
Payload columns default to "{}".
Report errors cap at 1000 chars.
Research validation has unique candidate_review_id.
Candidate report links are nullable and indexed.
```

Commit:

```bash
git add src/quant_trading/storage/models.py \
  src/quant_trading/storage/repositories.py \
  migrations/versions/20260626_0009_add_validation_reports.py \
  tests/integration/test_migrations.py \
  tests/integration/test_data_quality_reports_repository.py \
  tests/integration/test_research_validation_reports_repository.py
git commit -m "feat: add quant validation report storage"
```

---

### Task 2: Market Data Query Bounds And Data Quality Service

**Files:**
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `src/quant_trading/data/quality.py`
- Create: `tests/unit/test_data_quality.py`
- Modify: `tests/integration/test_storage_repositories.py`

- [ ] **Step 1: Write failing bounded data query test**

In `tests/integration/test_storage_repositories.py`, add:

```python
def test_market_data_repository_list_bars_filters_date_source_and_adjustment():
    # Seed rows with source='legacy' and source='akshare', adjusted='qfq' and adjusted='hfq'.
    # Call list_bars('000001') and list_bars('000001', start=date(2026, 1, 2), end=date(2026, 1, 2), source='akshare', adjusted='qfq').
    # Assert the filtered call returns only the expected single qfq AkShare bar.
    pass
```

Seed one instrument with bars across two dates, two sources, and two adjustments. Assert:

```python
assert [bar.timestamp.isoformat() for bar in all_bars] == [
    "2026-01-01",
    "2026-01-02",
    "2026-01-03",
]
assert [bar.timestamp.isoformat() for bar in filtered] == ["2026-01-02"]
assert filtered[0].source == "akshare"
assert filtered[0].adjusted.value == "qfq"
```

- [ ] **Step 2: Write failing data quality unit tests**

Create `tests/unit/test_data_quality.py`.

Test names:

```python
def test_assess_bars_quality_passes_clean_data():
    # Build 120 weekday bars and assert status='passed', severity='none', and no findings.
    pass

def test_assess_bars_quality_fails_duplicate_timestamps():
    # Duplicate one timestamp and assert duplicate_timestamp_count=1 and status='failed'.
    pass

def test_assess_bars_quality_fails_non_positive_prices():
    # Set close=Decimal('0') on one bar and assert non_positive_price_count=1.
    pass

def test_assess_bars_quality_fails_invalid_ohlc():
    # Create one bar with high < low and assert invalid_ohlc_count=1.
    pass

def test_assess_bars_quality_flags_medium_missing_coverage():
    # Request a wider weekday range than the supplied bars and assert status='needs_review'.
    pass

def test_assess_bars_quality_handles_zero_expected_count_without_division_error():
    # Pass requested_start=requested_end=None and no bars; assert status='failed' via bar_count < 120.
    pass

def test_data_fingerprint_is_stable_and_changes_when_values_change():
    # Compute fingerprint twice for identical sorted bars, then change close/source/adjusted and assert it changes.
    pass
```

Use a helper:

```python
def make_bar(day: date, close: Decimal = Decimal("10"), volume: Decimal = Decimal("1000")) -> Bar:
    return Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=day,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=volume,
        source="akshare",
        adjusted=Adjustment.QFQ,
    )
```

Required assertions:

```python
assert report["status"] == "passed"
assert report["severity"] == "none"
assert report["bar_count"] == 120
assert len(report["data_fingerprint"]) == 64
assert report["duplicate_timestamp_count"] == 1
assert report["non_positive_price_count"] == 1
assert report["invalid_ohlc_count"] == 1
assert report["status"] in {"failed", "needs_review"}
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_data_quality.py \
  tests/integration/test_storage_repositories.py::test_market_data_repository_list_bars_filters_date_source_and_adjustment \
  -q
```

Expected: FAIL because `quant_trading.data.quality` and `list_bars()` filters do not exist.

- [ ] **Step 4: Extend `MarketDataRepository.list_bars()`**

Change the signature in `src/quant_trading/storage/repositories.py`:

```python
def list_bars(
    self,
    symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
    source: str | None = None,
    adjusted: str | None = None,
) -> list[Bar]:
```

Build the statement incrementally:

```python
statement = (
    select(MarketBarORM)
    .join(InstrumentORM)
    .where(InstrumentORM.symbol == symbol)
    .order_by(MarketBarORM.timestamp)
)
if start is not None:
    statement = statement.where(MarketBarORM.timestamp >= start)
if end is not None:
    statement = statement.where(MarketBarORM.timestamp <= end)
if source:
    statement = statement.where(MarketBarORM.source == source)
if adjusted:
    statement = statement.where(MarketBarORM.adjusted == adjusted)
rows = self.session.scalars(statement).all()
```

Keep existing `Bar mapping` mapping unchanged.

- [ ] **Step 5: Implement `src/quant_trading/data/quality.py`**

Create constants:

```python
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_NEEDS_REVIEW = "needs_review"
SEVERITY_NONE = "none"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"
```

Implement:

```python
def assess_bars_quality(
    bars: list[Bar],
    *,
    requested_start: date | None,
    requested_end: date | None,
    now: date | None = None,
) -> dict[str, Any]:
```

The `now` parameter is test-only and defaults to `datetime.now(UTC).date()`.

Return a dict containing every report count, `status`, `severity`, `data_fingerprint`,
and:

```python
"findings_payload": {
    "findings": findings,
    "range": {"start": _iso(start_date), "end": _iso(end_date)},
}
```

Implement helpers:

```python
def _weekday_count(start: date, end: date) -> int:
    # Count Monday-Friday dates inclusively.
    pass

def _fingerprint(bars: list[Bar]) -> str:
    # Return SHA-256 over sorted symbol|timestamp|open|high|low|close|volume|source|adjusted rows.
    pass

def _highest_status(findings: list[dict[str, Any]]) -> tuple[str, str]:
    # Return ('failed', 'high') when any high finding exists, ('needs_review', 'medium')
    # when any medium finding exists, otherwise ('passed', 'none').
    pass
```

- [ ] **Step 6: Add persisted report creation**

In `src/quant_trading/data/quality.py`, implement:

```python
def build_data_quality_report(
    engine: Engine,
    *,
    symbol: str,
    candidate_review_id: int | None = None,
    backtest_run_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    job_run_id: int | None = None,
) -> dict[str, Any]:
```

Use `MarketDataRepository(session).list_bars(symbol, start=start, end=end)` and `DataQualityReportRepository`.

Return:

```python
{
    "report_id": report.id,
    "symbol": report.symbol,
    "status": report.status,
    "severity": report.severity,
    "bar_count": report.bar_count,
    "data_fingerprint": report.data_fingerprint,
}
```

When `candidate_review_id` is provided, link the report through `AgentCandidateReviewRepository.link_data_quality_report()`.

- [ ] **Step 7: Run data quality tests**

Run:

```bash
pytest tests/unit/test_data_quality.py \
  tests/integration/test_storage_repositories.py::test_market_data_repository_list_bars_filters_date_source_and_adjustment \
  -q
```

Expected: PASS.

- [ ] **Step 8: Run task review and commit**

Spec review checklist:

```text
Task 2 covers Data Quality Rules and Backtest Slice Support query bounds.
It does not add validation orchestration, LLM behavior, paper runs, or broker calls.
```

Quality review checklist:

```text
No divide-by-zero in missing coverage or volume ratios.
Fingerprint is deterministic and sorted.
Existing list_bars(symbol) callers still work.
Report creation links candidate only when candidate_review_id is provided.
```

Commit:

```bash
git add src/quant_trading/storage/repositories.py \
  src/quant_trading/data/quality.py \
  tests/unit/test_data_quality.py \
  tests/integration/test_storage_repositories.py
git commit -m "feat: add market data quality reports"
```

---

### Task 3: Backtest Slicing And Validation Metrics

**Files:**
- Modify: `src/quant_trading/backtest/engine.py`
- Create: `src/quant_trading/validation/__init__.py`
- Create: `src/quant_trading/validation/metrics.py`
- Create: `tests/unit/test_research_validation_metrics.py`
- Modify: `tests/integration/test_backtest_engine.py`

- [ ] **Step 1: Write failing backtest slicing test**

In `tests/integration/test_backtest_engine.py`, add:

```python
def test_backtest_engine_run_respects_date_bounds():
    # Seed 10 daily bars, run BacktestEngine.run(start=2026-01-04, end=2026-01-08),
    # and assert the summary contains exactly 5 equity points.
    pass
```

Seed 10 daily bars and run:

```python
summary = BacktestEngine(
    engine=engine,
    initial_cash=Decimal("100000"),
    commission_rate=Decimal("0.0003"),
    slippage_rate=Decimal("0.001"),
).run(
    symbol="000001",
    strategy=MACrossStrategy(short_window=2, long_window=3, order_size=100),
    strategy_name="ma_cross",
    start=date(2026, 1, 4),
    end=date(2026, 1, 8),
)
```

Assert:

```python
assert summary.equity_points == 5
```

- [ ] **Step 2: Write failing metrics tests**

Create `tests/unit/test_research_validation_metrics.py`.

Test names:

```python
def test_cap_readiness_never_exceeds_floor():
    # Assert each readiness value is capped according to READINESS_ORDER.
    pass

def test_backtest_metric_payload_handles_empty_orders():
    # Seed a BacktestRunORM with equity points but no orders/fills and assert safe zero metrics.
    pass

def test_buy_and_hold_benchmark_returns_metrics_without_persisting_orders():
    # Pass three bars to buy_and_hold_benchmark() and assert no BacktestOrderORM rows are needed.
    pass
```

Required assertions for readiness:

```python
assert cap_readiness("ready_for_paper_research", "not_ready") == ("not_ready", True)
assert cap_readiness("ready_for_paper_research", "needs_review") == ("needs_review", True)
assert cap_readiness("needs_review", "ready_for_paper_research") == ("needs_review", False)
assert cap_readiness("not_ready", "ready_for_paper_research") == ("not_ready", False)
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_research_validation_metrics.py \
  tests/integration/test_backtest_engine.py::test_backtest_engine_run_respects_date_bounds \
  -q
```

Expected: FAIL because metrics helpers and date-bounded backtest signature do not exist.

- [ ] **Step 4: Update `BacktestEngine.run()` signature**

In `src/quant_trading/backtest/engine.py`, change:

```python
def run(
    self,
    symbol: str,
    strategy: Strategy,
    strategy_name: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> BacktestSummary:
```

Load bars with:

```python
bars = MarketDataRepository(session).list_bars(symbol, start=start, end=end)
```

Existing callers pass no bounds and keep existing behavior.

- [ ] **Step 5: Implement metrics module**

Create `src/quant_trading/validation/__init__.py`:

```python
"""Research validation helpers for Quant Agent."""
```

Create `src/quant_trading/validation/metrics.py` with:

```python
READINESS_ORDER = {
    "not_ready": 0,
    "needs_review": 1,
    "ready_for_paper_research": 2,
}


def cap_readiness(value: str, floor: str) -> tuple[str, bool]:
    value_rank = READINESS_ORDER.get(value, READINESS_ORDER["needs_review"])
    floor_rank = READINESS_ORDER.get(floor, READINESS_ORDER["not_ready"])
    if value_rank > floor_rank:
        capped = next(key for key, rank in READINESS_ORDER.items() if rank == floor_rank)
        return capped, True
    return value if value in READINESS_ORDER else "needs_review", False
```

Add:

```python
def decimal_string(value: Decimal) -> str:
    # Normalize Decimal output without scientific notation.
    pass

def metric_payload_from_run(session: Session, run: BacktestRunORM) -> dict[str, Any]:
    # Read equity points, orders, and fills for run.id and return the metric JSON shape from the spec.
    pass

def buy_and_hold_benchmark(
    bars: list[Bar],
    *,
    initial_cash: Decimal,
    commission_rate: Decimal,
    slippage_rate: Decimal,
) -> dict[str, Any]:
    # Compute first-close buy-and-hold metrics without writing database rows.
    pass
```

Use safe zeros when orders/fills are missing.

- [ ] **Step 6: Run metrics tests**

Run:

```bash
pytest tests/unit/test_research_validation_metrics.py \
  tests/integration/test_backtest_engine.py::test_backtest_engine_run_respects_date_bounds \
  tests/integration/test_backtest_engine.py \
  -q
```

Expected: PASS.

- [ ] **Step 7: Run task review and commit**

Spec review checklist:

```text
Task 3 covers Backtest Slice Support, Validation Metrics, Benchmark helper, and readiness cap helper.
It does not create validation jobs or alter agent behavior yet.
```

Quality review checklist:

```text
Existing backtest callers are backward-compatible.
Metrics use Decimal-safe string output.
Empty trades and zero initial cash do not crash.
Benchmark does not persist backtest orders.
```

Commit:

```bash
git add src/quant_trading/backtest/engine.py \
  src/quant_trading/validation/__init__.py \
  src/quant_trading/validation/metrics.py \
  tests/unit/test_research_validation_metrics.py \
  tests/integration/test_backtest_engine.py
git commit -m "feat: add validation metrics and sliced backtests"
```

---

### Task 4: Research Validation Service

**Files:**
- Create: `src/quant_trading/validation/research.py`
- Create: `tests/integration/test_validation_jobs.py`
- Modify: `src/quant_trading/storage/repositories.py`

- [ ] **Step 1: Write failing research validation service tests**

In `tests/integration/test_validation_jobs.py`, add service tests:

```python
def test_run_candidate_research_validation_persists_passed_report():
    # Seed a valid candidate review and 300 clean bars, run validation, and assert report payloads are populated.
    pass

def test_run_candidate_research_validation_fails_when_data_quality_fails():
    # Seed insufficient or invalid bars, run validation, and assert validation_status='failed'.
    pass

def test_run_candidate_research_validation_updates_existing_report_on_rerun():
    # Run validation twice for the same candidate_review_id and assert one report row remains.
    pass

def test_run_candidate_research_validation_creates_no_paper_or_broker_rows():
    # Count paper and broker rows before/after validation and assert both counts stay zero.
    pass
```

Seed helpers must create:

- instrument and at least 300 daily bars;
- a succeeded `strategy_idea` agent run with `ma_cross` candidate payload;
- an approved candidate review in `backtest_succeeded` status;
- a linked source `backtest_run_id`.

Required assertions:

```python
assert result["validation_status"] in {"passed", "needs_review"}
assert result["candidate_review_id"] == candidate_review_id
assert result["research_validation_report_id"] > 0
assert result["data_quality_report_id"] > 0
assert report.source_backtest_run_id == backtest_run_id
assert report.out_of_sample_metrics_payload != "{}"
assert report.walk_forward_payload != "{}"
assert report.parameter_sensitivity_payload != "{}"
assert report.benchmark_payload != "{}"
assert paper_run_count == 0
assert broker_event_count == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/integration/test_validation_jobs.py::test_run_candidate_research_validation_persists_passed_report \
  -q
```

Expected: FAIL because `run_candidate_research_validation()` does not exist.

- [ ] **Step 3: Implement validation errors and helpers**

In `src/quant_trading/validation/research.py`, create:

```python
class ResearchValidationError(ValueError):
    pass


class ResearchValidationNotFoundError(ResearchValidationError):
    pass


class ResearchValidationConflictError(ResearchValidationError):
    pass
```

Add helpers:

```python
ELIGIBLE_CANDIDATE_STATUSES = {
    "backtest_succeeded",
    "review_requested",
    "review_succeeded",
    "review_failed",
}


def _json_loads(value: str | None) -> dict[str, Any]:
    # Return {} for empty values and raise ResearchValidationConflictError for non-object JSON.
    pass


def _json_dumps(payload: dict[str, Any]) -> str:
    # Dump compact sorted JSON with default=str.
    pass


def _parse_payload(review: AgentCandidateReviewORM) -> dict[str, Any]:
    # Validate the stored backtest_request_payload and return its payload object.
    pass


def _split_70_30(bars: list[Bar]) -> tuple[list[Bar], list[Bar]]:
    # Split sorted bars into first 70 percent and final 30 percent.
    pass


def _walk_forward_windows(bars: list[Bar]) -> list[tuple[date, date]]:
    # Build 180-train/60-test rolling test windows with 60-bar step.
    pass


def _parameter_grid(short_window: int, long_window: int) -> list[tuple[int, int]]:
    # Return up to 9 valid (short, long) pairs using deltas [-2,0,+2] and [-5,0,+5].
    pass
```

- [ ] **Step 4: Implement orchestration**

Implement:

```python
def run_candidate_research_validation(
    engine: Engine,
    *,
    candidate_review_id: int,
    job_run_id: int | None = None,
) -> dict[str, Any]:
```

Flow:

1. Create or reset a `ResearchValidationReportORM` row with `validation_status="running"`.
2. Load candidate review and source backtest run.
3. Validate candidate status, strategy name, `backtest_run_id`, and stored backtest payload.
4. Run `build_data_quality_report()` for full available symbol history.
5. Link report IDs on the candidate review.
6. If data quality failed, mark validation failed and return early.
7. Load bars, split windows, run in-sample and out-of-sample MA Cross backtests with date bounds.
8. Run walk-forward windows and parameter grid.
9. Run benchmark helper.
10. Determine `validation_status` and `readiness_floor`.
11. Mark report completed and return a compact payload.

Every generated historical backtest payload section must include `backtest_run_id`.

- [ ] **Step 5: Add progress callback support**

Keep the public signature ready for runtime integration:

```python
def run_candidate_research_validation(
    engine: Engine,
    *,
    candidate_review_id: int,
    job_run_id: int | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
```

Call `cancellation_token.raise_if_cancelled()` before each major section when provided.
Call `progress_callback(progress, message)` with the messages from the spec when provided.

- [ ] **Step 6: Run research validation service tests**

Run:

```bash
pytest tests/integration/test_validation_jobs.py::test_run_candidate_research_validation_persists_passed_report \
  tests/integration/test_validation_jobs.py::test_run_candidate_research_validation_fails_when_data_quality_fails \
  tests/integration/test_validation_jobs.py::test_run_candidate_research_validation_updates_existing_report_on_rerun \
  tests/integration/test_validation_jobs.py::test_run_candidate_research_validation_creates_no_paper_or_broker_rows \
  -q
```

Expected: PASS.

- [ ] **Step 7: Run task review and commit**

Spec review checklist:

```text
Task 4 covers Research Validation Service, Validation Status Rules, generated backtest artifact traceability, and rerun update-in-place behavior.
It does not add API endpoints or LLM behavior yet.
```

Quality review checklist:

```text
Candidate payload is read from persisted approval only.
Validation never mutates backtest_request_payload.
Data-quality failed path exits without validation details.
Reruns update the existing report row.
Side-effect test proves no paper or broker rows.
```

Commit:

```bash
git add src/quant_trading/validation/research.py \
  src/quant_trading/storage/repositories.py \
  tests/integration/test_validation_jobs.py
git commit -m "feat: add quant research validation service"
```

---

### Task 5: Job Runtime And Report APIs

**Files:**
- Modify: `src/quant_trading/jobs/runtime.py`
- Modify: `src/quant_trading/api/routes/jobs.py`
- Create: `src/quant_trading/api/routes/data_quality_reports.py`
- Create: `src/quant_trading/api/routes/research_validation_reports.py`
- Modify: `src/quant_trading/api/main.py`
- Modify: `tests/integration/test_validation_jobs.py`

- [ ] **Step 1: Write failing job/API tests**

In `tests/integration/test_validation_jobs.py`, add:

```python
def test_data_quality_report_job_api_persists_report(client):
    # POST /jobs/data-quality/report and assert the inline job result links a persisted report.
    pass

def test_research_validation_job_api_persists_report(client):
    # POST /jobs/validation/research and assert the inline job result links a persisted validation report.
    pass

def test_report_read_apis_return_decoded_payloads(client):
    # GET individual report endpoints and assert JSON text columns are decoded to dictionaries.
    pass

def test_report_read_apis_filter_recent_reports(client):
    # GET list endpoints with symbol/status/severity/validation_status filters and assert expected ids.
    pass
```

Required assertions:

```python
assert payload["job_type"] == "data_quality_report"
assert payload["status"] in {"queued", "running", "succeeded"}
assert report_payload["findings_payload"]["findings"] == []
assert validation_payload["summary_payload"]["reasons"] == []
assert listed[0]["id"] == report_id
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/integration/test_validation_jobs.py::test_data_quality_report_job_api_persists_report \
  tests/integration/test_validation_jobs.py::test_research_validation_job_api_persists_report \
  -q
```

Expected: FAIL because job types and API routes do not exist.

- [ ] **Step 3: Add runtime job types**

In `src/quant_trading/jobs/runtime.py`, add:

```python
from quant_trading.data.quality import build_data_quality_report
from quant_trading.validation.research import run_candidate_research_validation

DATA_QUALITY_REPORT = "data_quality_report"
RESEARCH_VALIDATION = "research_validation"
```

Add both to `SUPPORTED_JOB_TYPES`.

In `_execute_payload()`:

```python
if job_type == DATA_QUALITY_REPORT:
    return build_data_quality_report(
        engine,
        symbol=str(payload["symbol"]),
        candidate_review_id=int(payload["candidate_review_id"])
        if payload.get("candidate_review_id")
        else None,
        backtest_run_id=int(payload["backtest_run_id"])
        if payload.get("backtest_run_id")
        else None,
        start=date.fromisoformat(payload["start"]) if payload.get("start") else None,
        end=date.fromisoformat(payload["end"]) if payload.get("end") else None,
        job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
    )
if job_type == RESEARCH_VALIDATION:
    return run_candidate_research_validation(
        engine,
        candidate_review_id=int(payload["candidate_review_id"]),
        job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
        cancellation_token=cancellation_token,
        progress_callback=progress_callback,
    )
```

Ensure `execute_job_run_with_engine()` injects `job_run_id` into these payloads the same way it already does for market data sync and agent jobs.

- [ ] **Step 4: Add job submission endpoints**

In `src/quant_trading/api/routes/jobs.py`, add request models:

```python
class DataQualityReportRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    candidate_review_id: int | None = Field(default=None, gt=0)
    backtest_run_id: int | None = Field(default=None, gt=0)
    start: str | None = None
    end: str | None = None


class ResearchValidationRequest(BaseModel):
    candidate_review_id: int = Field(gt=0)
```

Add endpoints:

```python
@router.post("/data-quality/report")
def create_data_quality_report_job(
    payload: DataQualityReportRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            DATA_QUALITY_REPORT,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )


@router.post("/validation/research")
def create_research_validation_job(
    payload: ResearchValidationRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            RESEARCH_VALIDATION,
            payload.model_dump(mode="json"),
            make_queue,
        )
    )
```

- [ ] **Step 5: Add report read APIs**

Create `src/quant_trading/api/routes/data_quality_reports.py`, following `data_sync.py` style:

```python
router = APIRouter(prefix="/data-quality-reports", tags=["data-quality-reports"])
```

Expose:

```python
@router.get("")
def list_data_quality_reports(
    request: Request,
    symbol: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    candidate_review_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    pass

@router.get("/{report_id}")
def get_data_quality_report(report_id: int, request: Request) -> dict[str, Any]:
    pass
```

Decode `findings_payload` with `json.loads()`.

Create `src/quant_trading/api/routes/research_validation_reports.py` with:

```python
router = APIRouter(
    prefix="/research-validation-reports",
    tags=["research-validation-reports"],
)
```

Decode all validation payload text columns.

- [ ] **Step 6: Register routers**

In `src/quant_trading/api/main.py`, import and include:

```python
data_quality_reports,
research_validation_reports,
```

Register before dashboard:

```python
app.include_router(data_quality_reports.router)
app.include_router(research_validation_reports.router)
```

- [ ] **Step 7: Run job/API tests**

Run:

```bash
pytest tests/integration/test_validation_jobs.py \
  tests/integration/test_jobs_api.py \
  tests/integration/test_job_runtime.py \
  -q
```

Expected: PASS.

- [ ] **Step 8: Run task review and commit**

Spec review checklist:

```text
Task 5 covers Job Runtime, API Behavior, report read endpoints, filters, decoded payload responses, and error mapping foundations.
It does not change backtest_review gate yet.
```

Quality review checklist:

```text
Job payloads do not contain API keys.
Job_run_id is injected for persisted report linkage.
List limits clamp to 1..100.
Read routes return 404 for missing reports.
```

Commit:

```bash
git add src/quant_trading/jobs/runtime.py \
  src/quant_trading/api/routes/jobs.py \
  src/quant_trading/api/routes/data_quality_reports.py \
  src/quant_trading/api/routes/research_validation_reports.py \
  src/quant_trading/api/main.py \
  tests/integration/test_validation_jobs.py
git commit -m "feat: expose quant validation report jobs"
```

---

### Task 6: Backtest Review Validation Gate And Readiness Cap

**Files:**
- Modify: `src/quant_trading/agents/models.py`
- Modify: `src/quant_trading/agents/backtest_review.py`
- Modify: `src/quant_trading/agents/service.py`
- Modify: `src/quant_trading/api/routes/jobs.py`
- Modify: `src/quant_trading/api/routes/agent_candidates.py`
- Modify: `tests/unit/test_backtest_review_agent.py`
- Modify: `tests/integration/test_agents_jobs.py`
- Modify: `tests/integration/test_agent_candidates_api.py`

- [ ] **Step 1: Write failing review gate tests**

In `tests/integration/test_agents_jobs.py`, add:

```python
def test_run_backtest_review_agent_rejects_missing_validation_report_without_agent_row():
    # Seed a backtest_succeeded candidate without validation links and assert review rejects before creating AgentRunORM.
    pass

def test_run_backtest_review_agent_allows_explicit_validation_override():
    # Call BacktestReviewRequest(require_validation_report=False) and assert legacy review path still works.
    pass

def test_run_backtest_review_agent_caps_readiness_by_validation_floor():
    # Seed validation readiness_floor='not_ready', fake LLM returns ready_for_paper_research, assert result is not_ready.
    pass
```

Required assertions:

```python
with pytest.raises(ValueError, match="validation report is required"):
    run_backtest_review_agent(engine, BacktestReviewRequest(candidate_review_id=candidate_review_id))
assert session.scalar(select(func.count(AgentRunORM.id)).where(AgentRunORM.agent_type == "backtest_review")) == 0
assert result["paper_trading_readiness"] == "not_ready"
assert result["readiness_floor_applied"] is True
assert result["validation_report_id"] == validation_report_id
assert result["data_quality_report_id"] == data_quality_report_id
```

- [ ] **Step 2: Write failing context unit test**

In `tests/unit/test_backtest_review_agent.py`, add:

```python
def test_load_backtest_review_context_includes_validation_and_data_quality_reports():
    # Seed linked data_quality_report_id and research_validation_report_id on a candidate review,
    # call load_backtest_review_context(), and assert both compact report summaries are present.
    pass
```

Required assertions:

```python
assert context["data_quality_report"]["id"] == data_quality_report_id
assert context["data_quality_report"]["status"] == "passed"
assert context["research_validation_report"]["id"] == validation_report_id
assert context["research_validation_report"]["readiness_floor"] == "not_ready"
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_backtest_review_agent.py::test_load_backtest_review_context_includes_validation_and_data_quality_reports \
  tests/integration/test_agents_jobs.py::test_run_backtest_review_agent_rejects_missing_validation_report_without_agent_row \
  -q
```

Expected: FAIL because context loading and request model do not include validation reports.

- [ ] **Step 4: Extend request models**

In `src/quant_trading/agents/models.py`, change:

```python
@dataclass(frozen=True)
class BacktestReviewRequest:
    candidate_review_id: int
    backtest_run_id: int | None = None
    require_validation_report: bool = True
```

In `src/quant_trading/api/routes/jobs.py`, extend `AgentBacktestReviewRequest`:

```python
require_validation_report: bool = True
```

In `src/quant_trading/jobs/runtime.py`, pass the field into `BacktestReviewRequest`.

- [ ] **Step 5: Extend backtest review context**

In `src/quant_trading/agents/backtest_review.py`, load linked report rows from the candidate review IDs. Add payload helpers:

```python
def _data_quality_report_payload(row: DataQualityReportORM | None) -> dict[str, Any] | None:
    # Return None for missing rows; otherwise return id, status, severity, counts, and data_fingerprint.
    pass


def _research_validation_report_payload(
    row: ResearchValidationReportORM | None,
) -> dict[str, Any] | None:
    # Return None for missing rows; otherwise return id, validation_status, readiness_floor, and compact decoded summaries.
    pass
```

Include compact decoded payloads:

```python
"data_quality_report": _data_quality_report_payload(data_quality_report),
"research_validation_report": _research_validation_report_payload(validation_report),
```

- [ ] **Step 6: Enforce validation report before agent row creation**

In `src/quant_trading/agents/service.py`, after context load and before `AgentRunRepository.create_running()`:

```python
validation_report = context.get("research_validation_report")
if request.require_validation_report and not validation_report:
    raise ValueError("validation report is required for backtest review")
```

Keep this check before agent row creation so rejected requests create no `agent_runs` row.

- [ ] **Step 7: Cap readiness after parsing**

Import `cap_readiness()` from `quant_trading.validation.metrics`.

After `parse_backtest_review_response()`:

```python
readiness_floor = str(validation_report.get("readiness_floor") or "not_ready") if validation_report else "ready_for_paper_research"
capped_readiness, floor_applied = cap_readiness(
    str(parsed_payload.get("paper_trading_readiness") or "needs_review"),
    readiness_floor,
)
parsed_payload["paper_trading_readiness"] = capped_readiness
parsed_payload["readiness_floor_applied"] = floor_applied
parsed_payload["validation_report_id"] = validation_report.get("id") if validation_report else None
parsed_payload["data_quality_report_id"] = (
    context.get("data_quality_report") or {}
).get("id")
```

- [ ] **Step 8: Extend candidate payloads**

In `src/quant_trading/agents/candidate_reviews.py` and `src/quant_trading/api/routes/agent_candidates.py` payload paths, include:

```python
"data_quality_report_id": row.data_quality_report_id,
"research_validation_report_id": row.research_validation_report_id,
```

Add API assertions in `tests/integration/test_agent_candidates_api.py`.

- [ ] **Step 9: Run backtest review tests**

Run:

```bash
pytest tests/unit/test_backtest_review_agent.py \
  tests/integration/test_agents_jobs.py \
  tests/integration/test_agent_candidates_api.py \
  -q
```

Expected: PASS.

- [ ] **Step 10: Run task review and commit**

Spec review checklist:

```text
Task 6 covers Agent Integration, missing validation 409 behavior through API/job tests, readiness cap, report IDs in candidate payloads, and legacy override.
It does not create paper runs or broker rows.
```

Quality review checklist:

```text
Missing validation check happens before agent row creation.
Readiness cap handles unknown values conservatively.
Prompt context avoids dumping oversized validation payloads.
Existing parser unsafe-text checks remain intact.
```

Commit:

```bash
git add src/quant_trading/agents/models.py \
  src/quant_trading/agents/backtest_review.py \
  src/quant_trading/agents/service.py \
  src/quant_trading/jobs/runtime.py \
  src/quant_trading/api/routes/jobs.py \
  src/quant_trading/api/routes/agent_candidates.py \
  src/quant_trading/agents/candidate_reviews.py \
  tests/unit/test_backtest_review_agent.py \
  tests/integration/test_agents_jobs.py \
  tests/integration/test_agent_candidates_api.py
git commit -m "feat: gate backtest review on validation reports"
```

---

### Task 7: README, Regression Suite, And Final Review

**Files:**
- Modify: `README.md`
- Verify: all changed tests and full compile/test commands

- [ ] **Step 1: Update README Quant Agent section**

Under `Quant Agent`, add a subsection:

```markdown
### Quant Agent v4: research validation and data quality

V4 adds deterministic evidence gates before `backtest_review` can make a research
readiness recommendation by default:

```text
candidate approval -> in-sample backtest -> data quality report -> research validation report -> backtest_review
```

Create a data quality report job:

```bash
curl -X POST http://127.0.0.1:8000/jobs/data-quality/report \
  -H "Content-Type: application/json" \
  -d '{"symbol":"000001","candidate_review_id":1,"backtest_run_id":1}'
```

Create a research validation job:

```bash
curl -X POST http://127.0.0.1:8000/jobs/validation/research \
  -H "Content-Type: application/json" \
  -d '{"candidate_review_id":1}'
```

Read reports:

```bash
curl http://127.0.0.1:8000/data-quality-reports
curl http://127.0.0.1:8000/research-validation-reports
```

Backtest review jobs require a linked validation report by default. The request accepts
`require_validation_report=false` only for explicit legacy local research.

Validation output remains research-only. It does not create paper runs, approve paper
trading, call broker adapters, place orders, or execute generated code.
```

- [ ] **Step 2: Run focused verification**

Run:

```bash
pytest \
  tests/unit/test_data_quality.py \
  tests/unit/test_research_validation_metrics.py \
  tests/integration/test_data_quality_reports_repository.py \
  tests/integration/test_research_validation_reports_repository.py \
  tests/integration/test_validation_jobs.py \
  tests/unit/test_backtest_review_agent.py \
  tests/integration/test_agents_jobs.py \
  tests/integration/test_migrations.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Run regression verification**

Run:

```bash
pytest tests/integration/test_agent_candidate_approval_service.py \
  tests/integration/test_agent_candidate_reviews_repository.py \
  tests/integration/test_agent_candidates_api.py \
  tests/integration/test_jobs_api.py \
  tests/integration/test_job_runtime.py \
  tests/integration/test_storage_repositories.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Run full compile**

Run:

```bash
python -m compileall -q src
```

Expected: exit 0.

- [ ] **Step 5: Run full suite if local time allows**

Run:

```bash
pytest -q
```

Expected: PASS. If external or time constraints prevent full suite completion, record the exact command, failure or timeout, and focused verification results in the final PR notes.

- [ ] **Step 6: Final spec review**

Check every acceptance criterion from the spec:

```text
1-3 report jobs and persistence: covered by tests/integration/test_validation_jobs.py
4-6 data quality rules: covered by tests/unit/test_data_quality.py
7-11 research validation rules: covered by tests/integration/test_validation_jobs.py
12-14 report and candidate read APIs: covered by tests/integration/test_validation_jobs.py and test_agent_candidates_api.py
15-17 backtest_review gate and readiness cap: covered by test_agents_jobs.py and test_backtest_review_agent.py
18 paper/broker isolation: covered by validation and agent integration side-effect assertions
19 secrets isolation: covered by payload assertions in job/API tests
20 v3 regression: covered by focused regression command
21 rerun update-in-place: covered by research validation repository/service tests
```

- [ ] **Step 7: Final quality review**

Check:

```text
No generated strategy code execution.
No broker adapter calls.
No paper run creation.
No automatic promotion to paper trading.
No uncapped readiness above validation floor.
No uncapped error messages.
No DeepSeek API key in persisted job/report/agent payloads.
SQLite migration upgrade and downgrade are reversible.
```

- [ ] **Step 8: Commit docs and any final fixes**

Commit:

```bash
git add README.md
git commit -m "docs: document quant validation workflow"
```

If final verification fixes touched code or tests, include those files in the same commit only if they are directly related to the final docs/verification pass. Otherwise create a separate fix commit with a precise message.

---

## Execution Order

Run tasks in order:

```text
Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6 -> Task 7
```

Do not start Task 4 before Task 3 passes. Do not start Task 6 before Task 5 passes.

## Final Verification Before PR

Required commands:

```bash
pytest \
  tests/unit/test_data_quality.py \
  tests/unit/test_research_validation_metrics.py \
  tests/integration/test_data_quality_reports_repository.py \
  tests/integration/test_research_validation_reports_repository.py \
  tests/integration/test_validation_jobs.py \
  tests/unit/test_backtest_review_agent.py \
  tests/integration/test_agents_jobs.py \
  tests/integration/test_migrations.py \
  -q

pytest -q

python -m compileall -q src
```

Required final side-effect checks:

```python
assert paper_run_count == 0
assert broker_order_event_count == 0
assert "DEEPSEEK_API_KEY" not in persisted_payload_text
```

## Handoff Notes

- Prefer subagent-driven execution: one fresh subagent per task, then run the two-review protocol before committing that task.
- If executing inline, stop after each task for review and commit before moving on.
- Keep report payloads compact in agent prompt context. Detailed report JSON belongs in read APIs, not in the LLM prompt.
- Keep all status strings exact. Tests must assert exact strings so drift is caught early.
