# Quant Agent Research Validation And Data Quality Design

## Context

Quant Agent now has an operator-gated research loop: `strategy_idea` creates a
validated `ma_cross` candidate, an operator approves or rejects it, approval submits
the stored deterministic MA Cross backtest request, and `backtest_review` produces a
research-only readiness recommendation.

The next bottleneck is not strategy variety. It is research quality. A single in-sample
backtest can look convincing even when the data is bad, the parameter choice is fragile,
or the result fails outside the fitted window. This milestone adds two product-grade
gates before Quant Agent can call a candidate strong research: data quality reports and
research validation reports.

## Current State

Verified on 2026-06-26 in branch `codex/quant-agent-v3-approval-review-loop`.

| Area | Current behavior | Gap |
| --- | --- | --- |
| Candidate review | `agent_candidate_reviews` stores source agent run, operator decision, linked backtest job, linked backtest run, and review agent run. | No link to data quality or validation report rows. |
| Backtest review context | `load_backtest_review_context()` loads candidate review, source agent result, backtest run, and single-run metrics from `src/quant_trading/agents/backtest_review.py:190`. | Context has no data coverage, data fingerprint, out-of-sample result, walk-forward result, or parameter sensitivity summary. |
| Review gate | `run_backtest_review_agent()` only requires `candidate_review.status == "backtest_succeeded"` in `src/quant_trading/agents/service.py:247`. | A review can run after one in-sample backtest even if data quality is unknown and validation has not run. |
| Backtest engine | `BacktestEngine.run()` reads all bars for a symbol from `MarketDataRepository.list_bars()` in `src/quant_trading/backtest/engine.py:44`. | It cannot run a deterministic date-bounded slice without adding a new query path or wrapper. |
| Market data storage | `market_bars` has unique identity by instrument, timestamp, timeframe, adjusted, and source in `src/quant_trading/storage/models.py:37`. | There is no persisted data snapshot or quality assessment for the bars used by a backtest. |
| Data sync validation | `validate_bars()` rejects duplicate provider bars and sorts by timestamp in `src/quant_trading/data/validation.py:4`. | It does not check missing sessions, stale coverage, non-positive OHLCV, impossible OHLC relationships, or suspicious zero volume. |
| Job runtime | `SUPPORTED_JOB_TYPES` includes import, MA Cross backtest, paper tick, market data sync, and agent jobs in `src/quant_trading/jobs/runtime.py:43`. | No job type exists for data quality or research validation. |
| API | Existing job APIs include `/jobs/backtests/ma-cross`, `/jobs/market-data/sync`, and `/jobs/agents/backtest-review` in `src/quant_trading/api/routes/jobs.py:72`. | No endpoint submits validation jobs or reads validation reports. |
| Migrations | Runtime migrations live in `migrations/versions/`; latest agent candidate review migration is `20260624_0008_add_agent_candidate_reviews.py`. | New report tables need a new `20260626_0009...` migration and migration test coverage. |

## Goal

Add a deterministic research validation layer and a persisted data quality layer for
approved Quant Agent candidates.

The end state:

```text
strategy_idea agent run
  -> human candidate approval
  -> in-sample backtest
  -> data quality report
  -> research validation report
  -> backtest_review agent reads all three evidence sources
  -> research-only readiness recommendation
```

The agent becomes more conservative when these reports fail. It must not promote a
strategy to paper trading, create paper runs, call broker adapters, or execute generated
strategy code.

## Proposed Change

Implement two new report types:

1. `data_quality_reports`: persisted health assessment of the market bars used for a
   candidate or validation run.
2. `research_validation_reports`: persisted deterministic validation summary for an
   approved candidate, including out-of-sample, walk-forward, parameter sensitivity, and
   benchmark comparison.

Both reports are deterministic service outputs. They do not call an LLM. The existing
`backtest_review` agent only consumes their summaries after they exist.

## Non-Goals

- No live trading.
- No paper run creation.
- No broker adapter calls.
- No order placement.
- No automatic promotion to paper trading.
- No arbitrary strategy template expansion.
- No execution of LLM-generated code.
- No LLM-driven modification of strategy parameters.
- No UI dashboard work in this milestone.
- No multi-symbol portfolio validation in this milestone.
- No external paid data-vendor integration in this milestone.

## Data Model

Add two ORM models in `src/quant_trading/storage/models.py`.

### `data_quality_reports`

```sql
CREATE TABLE data_quality_reports (
  id INTEGER PRIMARY KEY,
  candidate_review_id INTEGER NULL REFERENCES agent_candidate_reviews(id),
  backtest_run_id INTEGER NULL REFERENCES backtest_runs(id),
  job_run_id INTEGER NULL REFERENCES job_runs(id),
  symbol VARCHAR(32) NOT NULL,
  source VARCHAR(64) NOT NULL DEFAULT '',
  adjusted VARCHAR(16) NOT NULL DEFAULT '',
  start_date DATE NULL,
  end_date DATE NULL,
  bar_count INTEGER NOT NULL DEFAULT 0,
  expected_bar_count INTEGER NOT NULL DEFAULT 0,
  missing_bar_count INTEGER NOT NULL DEFAULT 0,
  duplicate_timestamp_count INTEGER NOT NULL DEFAULT 0,
  non_positive_price_count INTEGER NOT NULL DEFAULT 0,
  non_positive_volume_count INTEGER NOT NULL DEFAULT 0,
  invalid_ohlc_count INTEGER NOT NULL DEFAULT 0,
  stale_data BOOLEAN NOT NULL DEFAULT FALSE,
  data_fingerprint VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'running',
  severity VARCHAR(32) NOT NULL DEFAULT 'unknown',
  findings_payload TEXT NOT NULL DEFAULT '{}',
  created_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  duration_ms INTEGER NULL
);
```

Indexes:

- `candidate_review_id`
- `backtest_run_id`
- `job_run_id`
- `symbol`
- `status`
- `severity`
- `(symbol, start_date, end_date)`

Allowed `status` values:

- `running`
- `passed`
- `failed`
- `needs_review`

Allowed `severity` values:

- `none`
- `low`
- `medium`
- `high`
- `unknown`

### `research_validation_reports`

```sql
CREATE TABLE research_validation_reports (
  id INTEGER PRIMARY KEY,
  candidate_review_id INTEGER NOT NULL REFERENCES agent_candidate_reviews(id),
  source_backtest_run_id INTEGER NOT NULL REFERENCES backtest_runs(id),
  data_quality_report_id INTEGER NULL REFERENCES data_quality_reports(id),
  job_run_id INTEGER NULL REFERENCES job_runs(id),
  symbol VARCHAR(32) NOT NULL,
  strategy_name VARCHAR(128) NOT NULL,
  validation_status VARCHAR(32) NOT NULL DEFAULT 'running',
  readiness_floor VARCHAR(32) NOT NULL DEFAULT 'not_ready',
  in_sample_metrics_payload TEXT NOT NULL DEFAULT '{}',
  out_of_sample_metrics_payload TEXT NOT NULL DEFAULT '{}',
  walk_forward_payload TEXT NOT NULL DEFAULT '{}',
  parameter_sensitivity_payload TEXT NOT NULL DEFAULT '{}',
  benchmark_payload TEXT NOT NULL DEFAULT '{}',
  summary_payload TEXT NOT NULL DEFAULT '{}',
  error_message TEXT NULL,
  created_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  duration_ms INTEGER NULL
);
```

Indexes:

- `candidate_review_id`
- `source_backtest_run_id`
- `data_quality_report_id`
- `job_run_id`
- `symbol`
- `strategy_name`
- `validation_status`

`candidate_review_id` must be unique for this milestone. One candidate review gets
one latest validation report. Future iterations can add versioning if operators need
multiple validation passes.

If validation is run again for the same candidate review, the service must update the
existing report row in place: reset status to `running`, replace all validation payloads,
update `job_run_id`, clear stale `error_message`, and update timestamps. Do not create a
second `research_validation_reports` row for the same candidate review.

Allowed `validation_status` values:

- `running`
- `passed`
- `needs_review`
- `failed`

Allowed `readiness_floor` values:

- `not_ready`
- `needs_review`
- `ready_for_paper_research`

The `readiness_floor` is a cap, not an approval. If validation fails, the downstream
LLM parser must not return a stronger readiness than this value.

## Candidate Review Links

Add nullable columns to `agent_candidate_reviews`:

```sql
ALTER TABLE agent_candidate_reviews ADD COLUMN data_quality_report_id INTEGER NULL REFERENCES data_quality_reports(id);
ALTER TABLE agent_candidate_reviews ADD COLUMN research_validation_report_id INTEGER NULL REFERENCES research_validation_reports(id);
```

These columns let `GET /agent-candidates/{id}` expose the latest report IDs without
joining large JSON payloads into every list response.

## Data Quality Rules

Create `src/quant_trading/data/quality.py`.

Required public functions:

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
    ...

def assess_bars_quality(bars: list[Bar], *, requested_start: date | None, requested_end: date | None) -> dict[str, Any]:
    ...
```

Checks:

- `bar_count`: number of bars in the assessed range.
- `expected_bar_count`: weekday count between `start_date` and `end_date`.
- `missing_bar_count`: `max(0, expected_bar_count - bar_count)`. Use weekdays only for v1. Do not attempt exchange holiday calendars yet.
- `duplicate_timestamp_count`: count duplicate bar timestamps in the selected range.
- `non_positive_price_count`: count rows where any OHLC value is `<= 0`.
- `non_positive_volume_count`: count rows where volume is `<= 0`.
- `invalid_ohlc_count`: count rows where `high < max(open, close)` or `low > min(open, close)` or `high < low`.
- `stale_data`: true when `end_date` is more than 10 calendar days before the current UTC date.
- `data_fingerprint`: SHA-256 over sorted bar identity and values:
  `symbol|timestamp|open|high|low|close|volume|source|adjusted`.

Severity rules:

| Condition | Severity | Status |
| --- | --- | --- |
| `bar_count < 120` | `high` | `failed` |
| `duplicate_timestamp_count > 0` | `high` | `failed` |
| `non_positive_price_count > 0` | `high` | `failed` |
| `invalid_ohlc_count > 0` | `high` | `failed` |
| `missing_bar_count / expected_bar_count > 0.20` | `high` | `failed` |
| `missing_bar_count / expected_bar_count > 0.05` | `medium` | `needs_review` |
| `stale_data is true` | `medium` | `needs_review` |
| `non_positive_volume_count / bar_count > 0.10` | `medium` | `needs_review` |
| No findings | `none` | `passed` |

If several conditions apply, choose the highest severity and strictest status.
When `expected_bar_count == 0`, skip missing-coverage ratios and rely on `bar_count < 120`.
When `bar_count == 0`, skip volume ratios and fail through the insufficient-bars rule.

`findings_payload` must include machine-readable finding objects:

```json
{
  "findings": [
    {
      "code": "missing_bars_medium",
      "severity": "medium",
      "message": "Missing weekday bars exceed 5% of expected coverage.",
      "observed": 12,
      "threshold": 0.05
    }
  ],
  "range": {
    "start": "2025-01-01",
    "end": "2026-01-01"
  }
}
```

## Backtest Slice Support

Add a bounded market-data query before implementing validation:

```python
class MarketDataRepository:
    def list_bars(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
        source: str | None = None,
        adjusted: str | None = None,
    ) -> list[Bar]:
        ...
```

Existing calls with only `symbol` must keep returning the same full ordered history.

Update `BacktestEngine.run()` to accept optional `start` and `end`, then pass those
bounds into `MarketDataRepository.list_bars()`. This is the only implementation path for
v1 validation slicing.

The validation service must not mutate the approved candidate's original `backtest_request_payload`.

## Research Validation Service

Create `src/quant_trading/validation/research.py`.

Required public function:

```python
def run_candidate_research_validation(
    engine: Engine,
    *,
    candidate_review_id: int,
    job_run_id: int | None = None,
) -> dict[str, Any]:
    ...
```

Preconditions:

- Candidate review exists.
- Candidate review status is `backtest_succeeded`, `review_requested`, `review_succeeded`, or `review_failed`.
- Candidate review has `backtest_run_id`.
- Candidate review `strategy_name == "ma_cross"`.
- Candidate review `backtest_request_payload["job_type"] == "backtest_ma_cross"`.
- Candidate review `backtest_request_payload["payload"]` is used as the base parameter payload.

Steps:

1. Load the original candidate review, source backtest run, and base backtest request payload.
2. Run a data quality report for the candidate symbol and full available range.
3. If data quality status is `failed`, create a validation report with:
   - `validation_status="failed"`
   - `readiness_floor="not_ready"`
   - empty validation detail payloads
   - `summary_payload.reasons` containing the data quality finding codes
4. Split bars into in-sample and out-of-sample windows:
   - require at least 252 bars after data-quality filtering.
   - first 70% by timestamp is in-sample.
   - remaining 30% is out-of-sample.
   - if out-of-sample has fewer than 60 bars, mark `needs_review`.
5. Run deterministic MA Cross backtests for:
   - original parameters on in-sample window.
   - original parameters on out-of-sample window.
   - a buy-and-hold benchmark on the same out-of-sample window.
6. Run walk-forward validation:
   - use rolling windows of 180 train bars and 60 test bars.
   - step size is 60 bars.
   - require at least 2 folds, otherwise mark `needs_review`.
   - for each fold, run the original MA Cross parameters on the test slice.
7. Run parameter sensitivity:
   - evaluate short-window deltas `[-2, 0, +2]` with lower bound `2`.
   - evaluate long-window deltas `[-5, 0, +5]` with constraint `long_window > short_window`.
   - keep the original `order_size` and `initial_cash`.
   - skip invalid combinations.
   - include at most 9 combinations.
8. Store aggregate metrics and determine `validation_status`.

No validation run may create paper rows, broker order events, or paper job rows.
Every persisted validation payload section that is backed by a generated historical
backtest must include its `backtest_run_id` so operators can trace and clean up the
deterministic research artifacts.

## Validation Metrics

Create `src/quant_trading/validation/metrics.py`.

Required metrics for each tested run:

```json
{
  "initial_cash": "100000",
  "final_equity": "101234.56",
  "absolute_pnl": "1234.56",
  "return_pct": "1.23456",
  "max_drawdown_pct": "4.20000",
  "trade_count": 7,
  "win_rate": "0.57143",
  "turnover": "0.42000",
  "bar_count": 180
}
```

Metric definitions:

- `absolute_pnl = final_equity - initial_cash`.
- `return_pct = absolute_pnl / initial_cash * 100`.
- `max_drawdown_pct` uses the largest drawdown observed in equity points.
- `trade_count` counts filled backtest orders.
- `win_rate` can be approximate for v1: pair completed sell fills against the previous buy fill. If no completed pairs exist, return `"0"`.
- `turnover = sum(abs(fill.price * fill.quantity)) / initial_cash`.

If a metric cannot be computed, use a safe zero string and add a finding code in
`summary_payload.metric_warnings`.

## Benchmark

Implement a deterministic buy-and-hold benchmark for the out-of-sample window:

- buy as many shares as possible on the first bar close after commission and slippage assumptions used by MA Cross.
- hold through the final bar close.
- use the same `initial_cash` as the candidate payload.
- do not persist benchmark orders in `backtest_orders`; store only benchmark metrics in `benchmark_payload`.

Benchmark comparison result:

```json
{
  "strategy_return_pct": "1.20",
  "benchmark_return_pct": "3.40",
  "excess_return_pct": "-2.20",
  "strategy_max_drawdown_pct": "4.10",
  "benchmark_max_drawdown_pct": "6.00",
  "passed": false
}
```

## Validation Status Rules

Use conservative deterministic rules:

| Rule | Result |
| --- | --- |
| Data quality status is `failed` | `failed`, readiness floor `not_ready` |
| Out-of-sample return is negative | `needs_review`, readiness floor `not_ready` |
| Out-of-sample max drawdown is greater than 20% | `needs_review`, readiness floor `not_ready` |
| Fewer than 2 walk-forward folds | `needs_review`, readiness floor `not_ready` |
| More than half of walk-forward folds have negative return | `needs_review`, readiness floor `not_ready` |
| Parameter sensitivity median return is negative | `needs_review`, readiness floor `not_ready` |
| Original parameter return is in top 10% of sensitivity grid and median grid return is below 0 | `needs_review`, readiness floor `not_ready` |
| Strategy underperforms benchmark by more than 5 percentage points | `needs_review`, readiness floor `needs_review` |
| All required checks pass | `passed`, readiness floor `ready_for_paper_research` |

This milestone does not make any automatic paper-trading approval decision. A passed
validation only allows `backtest_review` to consider `ready_for_paper_research` as a
research recommendation.

## Agent Integration

Extend `load_backtest_review_context()` in `src/quant_trading/agents/backtest_review.py`.

New context keys:

```json
{
  "data_quality_report": {
    "id": 1,
    "status": "passed",
    "severity": "none",
    "bar_count": 520,
    "missing_bar_count": 0,
    "data_fingerprint": "..."
  },
  "research_validation_report": {
    "id": 1,
    "validation_status": "passed",
    "readiness_floor": "ready_for_paper_research",
    "out_of_sample_metrics": {},
    "walk_forward_summary": {},
    "parameter_sensitivity_summary": {},
    "benchmark": {}
  }
}
```

`run_backtest_review_agent()` must require a linked validation report unless the caller
passes an explicit override field:

```python
BacktestReviewRequest(
    candidate_review_id: int,
    backtest_run_id: int | None = None,
    require_validation_report: bool = True,
)
```

API default must be `require_validation_report=true`.

If validation is missing:

- raise a `409` conflict from the API layer.
- do not create an `agent_runs` row.
- do not call the LLM.

If validation exists but `readiness_floor` is weaker than the LLM output, the parser or
service must cap the final readiness:

```text
not_ready < needs_review < ready_for_paper_research
```

Examples:

- validation floor `not_ready`, LLM says `ready_for_paper_research` -> store `not_ready`.
- validation floor `needs_review`, LLM says `ready_for_paper_research` -> store `needs_review`.
- validation floor `ready_for_paper_research`, LLM says `needs_review` -> store `needs_review`.

The stored review payload must include:

```json
{
  "paper_trading_readiness": "needs_review",
  "readiness_floor_applied": true,
  "validation_report_id": 1,
  "data_quality_report_id": 1
}
```

## Job Runtime

Add job types in `src/quant_trading/jobs/runtime.py`:

```python
DATA_QUALITY_REPORT = "data_quality_report"
RESEARCH_VALIDATION = "research_validation"
```

Add them to `SUPPORTED_JOB_TYPES`.

Execution behavior:

- `DATA_QUALITY_REPORT` calls `build_data_quality_report()`.
- `RESEARCH_VALIDATION` calls `run_candidate_research_validation()`.
- Both support cancellation checks before each major validation section.
- Both record progress events when a progress callback is available.

Suggested progress for research validation:

| Progress | Message |
| --- | --- |
| 10 | `loading candidate and market data` |
| 25 | `running data quality checks` |
| 45 | `running out-of-sample validation` |
| 65 | `running walk-forward validation` |
| 80 | `running parameter sensitivity` |
| 90 | `running benchmark comparison` |
| 100 | `validation complete` |

## API Behavior

Add request models in `src/quant_trading/api/routes/jobs.py`.

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

Add job submission endpoints:

```text
POST /jobs/data-quality/report
POST /jobs/validation/research
```

Add read endpoints:

```text
GET /data-quality-reports
GET /data-quality-reports/{report_id}
GET /research-validation-reports
GET /research-validation-reports/{report_id}
```

List filters:

- `symbol`
- `status` for data quality reports.
- `severity` for data quality reports.
- `validation_status` for research validation reports.
- `candidate_review_id`.
- `limit`, clamped to `1..100`.

Extend `GET /agent-candidates/{candidate_review_id}` response with:

```json
{
  "data_quality_report_id": 1,
  "research_validation_report_id": 1
}
```

List responses include only IDs. Detailed report JSON must be read from report
endpoints.

## Error Handling

API mappings:

| Condition | HTTP |
| --- | --- |
| Candidate review not found | `404` |
| Backtest run not found | `404` |
| Data quality report not found | `404` |
| Research validation report not found | `404` |
| Candidate review has no backtest run | `409` |
| Candidate review status is not eligible for validation | `409` |
| Unsupported strategy template | `409` |
| Missing validation report when creating backtest review | `409` |
| Invalid date format or invalid range | `400` |

All persisted `error_message` values must be capped at 1000 characters.

## Safety Invariants

- Data quality jobs do not create `backtest_runs`, `paper_runs`, `broker_order_events`, or agent rows.
- Research validation jobs are allowed to create deterministic `backtest_runs`, `backtest_orders`, `backtest_fills`, and `backtest_equity_points` only for historical validation.
- Research validation jobs do not create `paper_runs`, `paper_orders`, broker rows, broker order events, or paper tick jobs.
- Backtest review jobs do not run if validation is missing unless `require_validation_report=false` is explicitly provided.
- Backtest review jobs never modify strategy parameters.
- Backtest review readiness cannot exceed the validation report `readiness_floor`.
- LLM output remains research-only and goes through the existing unsafe text parser.
- DeepSeek API keys must not appear in job payloads, workflow payloads, agent payloads, report payloads, or error messages.

## Implementation Details

### New modules

```text
src/quant_trading/data/quality.py
src/quant_trading/validation/__init__.py
src/quant_trading/validation/metrics.py
src/quant_trading/validation/research.py
src/quant_trading/api/routes/data_quality_reports.py
src/quant_trading/api/routes/research_validation_reports.py
```

### Existing modules to modify

```text
src/quant_trading/storage/models.py
src/quant_trading/storage/repositories.py
src/quant_trading/jobs/runtime.py
src/quant_trading/api/main.py
src/quant_trading/api/routes/jobs.py
src/quant_trading/api/routes/agent_candidates.py
src/quant_trading/agents/models.py
src/quant_trading/agents/backtest_review.py
src/quant_trading/agents/service.py
src/quant_trading/backtest/engine.py
README.md
tests/integration/test_migrations.py
```

### Migration

Add:

```text
migrations/versions/20260626_0009_add_validation_reports.py
```

`down_revision` must be `20260624_0008`.

The migration must:

1. create `data_quality_reports`;
2. create `research_validation_reports`;
3. add indexes listed above;
4. add nullable report link columns to `agent_candidate_reviews`;
5. downgrade cleanly by dropping added columns, indexes, and tables.

The migration must use Alembic operations that work with the project's SQLite test path.
If direct column drops are not portable for the installed Alembic/SQLite combination,
use `op.batch_alter_table("agent_candidate_reviews")` for upgrade and downgrade.

## Acceptance Criteria

1. `POST /jobs/data-quality/report` creates a `data_quality_report` job and returns a job payload.
2. `POST /jobs/validation/research` creates a `research_validation` job and returns a job payload.
3. A completed data quality job persists one `data_quality_reports` row with status, severity, counts, date range, and SHA-256 fingerprint.
4. Duplicate timestamps, invalid OHLC, non-positive OHLC prices, insufficient bars, and severe missing coverage produce `status="failed"`.
5. Medium missing coverage, stale data, or high zero-volume ratio produce `status="needs_review"`.
6. Clean data with at least 120 bars produces `status="passed"`.
7. A completed research validation job persists one `research_validation_reports` row linked to the candidate review and source backtest run.
8. Research validation runs out-of-sample, walk-forward, parameter sensitivity, and benchmark checks for `ma_cross`.
9. Research validation returns `failed` when linked data quality fails.
10. Research validation returns `needs_review` when out-of-sample, walk-forward, sensitivity, or benchmark rules fail.
11. Research validation returns `passed` only when all deterministic gates pass.
12. `GET /data-quality-reports/{id}` returns JSON-decoded `findings_payload`.
13. `GET /research-validation-reports/{id}` returns JSON-decoded validation payload fields.
14. `GET /agent-candidates/{id}` includes `data_quality_report_id` and `research_validation_report_id`.
15. `POST /jobs/agents/backtest-review` rejects missing validation reports with `409` by default and creates no `agent_runs` row in that case.
16. Backtest review prompt context includes data quality and research validation summaries when present.
17. Backtest review readiness is capped by `readiness_floor`.
18. No validation or review path creates paper runs, broker order events, or broker orders.
19. No report payload or job payload stores DeepSeek API keys.
20. Existing v3 candidate approval and backtest review tests continue to pass, except where tests intentionally opt into `require_validation_report=false` for legacy behavior.
21. Re-running research validation for the same candidate review updates the existing report row instead of creating a duplicate row.

## Testing Plan

| Layer | What | Count |
| --- | --- | --- |
| Unit | `assess_bars_quality()` clean data, duplicate timestamp, bad OHLC, non-positive price, zero volume, missing coverage, stale data | +7 |
| Unit | data fingerprint determinism and sensitivity to changed close/source/adjusted | +3 |
| Unit | validation metrics return, drawdown, win rate, turnover, empty trades | +5 |
| Unit | readiness cap helper for all readiness combinations | +4 |
| Integration | data quality repository create/get/list filters and JSON decoding | +4 |
| Integration | research validation repository create/get/list filters and candidate links | +4 |
| Integration | data quality job success/failure paths and no trading side effects | +3 |
| Integration | research validation job success, data-quality-failed, insufficient folds, benchmark underperformance | +4 |
| Integration | backtest review rejects missing validation by default and allows explicit legacy override | +2 |
| Integration | backtest review consumes reports and caps readiness | +2 |
| Integration | migration creates new tables, indexes, and candidate link columns | +1 |
| Regression | existing candidate approval loop and safety tests | existing suite |

Focused verification command for implementation:

```bash
python -m pytest \
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

Full verification before PR:

```bash
python -m pytest -q
python -m compileall -q src
```

## Rollback Plan

Code rollback:

- Revert the PR to remove the new job types, report services, API routes, and agent context changes.

Database rollback:

- For local development, run Alembic downgrade from `20260626_0009` to `20260624_0008`.
- The downgrade drops validation report tables and nullable report links from `agent_candidate_reviews`.
- Historical `backtest_runs` created by validation jobs are not automatically deleted. They are deterministic research artifacts and can be filtered by linked validation report before manual cleanup if needed.

Behavioral rollback:

- If validation gating blocks current workflows unexpectedly, temporarily submit `backtest_review` with `require_validation_report=false`. This override must stay explicit and must be documented as legacy research behavior.

## Effort Estimate

| Component | Estimate |
| --- | --- |
| Schema, migration, repositories | 3h |
| Data quality assessment service | 3h |
| Backtest slicing and validation metrics | 4h |
| Research validation orchestration | 5h |
| Job runtime and API routes | 3h |
| Backtest review context and readiness cap | 3h |
| Tests | 6h |
| README update and final verification | 2h |

Estimated total: 29h.

## Files Reference

| File | Change |
| --- | --- |
| `src/quant_trading/storage/models.py` | Add report ORM models and candidate review link columns. |
| `src/quant_trading/storage/repositories.py` | Add report repositories and extend candidate review payload support. |
| `migrations/versions/20260626_0009_add_validation_reports.py` | Add validation report schema migration. |
| `src/quant_trading/data/quality.py` | New data quality report service. |
| `src/quant_trading/validation/metrics.py` | New deterministic validation metric helpers. |
| `src/quant_trading/validation/research.py` | New candidate research validation service. |
| `src/quant_trading/backtest/engine.py` | Add bounded date support or validation-safe sliced runner. |
| `src/quant_trading/jobs/runtime.py` | Add `data_quality_report` and `research_validation` job types. |
| `src/quant_trading/api/routes/jobs.py` | Add job request models and submission endpoints. |
| `src/quant_trading/api/routes/data_quality_reports.py` | New read API for data quality reports. |
| `src/quant_trading/api/routes/research_validation_reports.py` | New read API for validation reports. |
| `src/quant_trading/api/main.py` | Register new routers. |
| `src/quant_trading/api/routes/agent_candidates.py` | Include report IDs in candidate payloads. |
| `src/quant_trading/agents/models.py` | Add `require_validation_report` to `BacktestReviewRequest`. |
| `src/quant_trading/agents/backtest_review.py` | Load report summaries into prompt context. |
| `src/quant_trading/agents/service.py` | Enforce validation presence and readiness cap. |
| `README.md` | Document the validation/data-quality loop and APIs. |
| `tests/unit/test_data_quality.py` | New unit tests for data checks. |
| `tests/unit/test_research_validation_metrics.py` | New unit tests for validation metrics. |
| `tests/integration/test_data_quality_reports_repository.py` | New repository tests. |
| `tests/integration/test_research_validation_reports_repository.py` | New repository tests. |
| `tests/integration/test_validation_jobs.py` | New job/API/service integration tests. |
| `tests/unit/test_backtest_review_agent.py` | Extend context and readiness cap coverage. |
| `tests/integration/test_agents_jobs.py` | Extend review gating and side-effect tests. |
| `tests/integration/test_migrations.py` | Assert new tables and candidate link columns. |

## Sequencing

```text
#1 Schema and repositories
  -> #2 Data quality service
  -> #3 Backtest slicing and metrics
  -> #4 Research validation service
  -> #5 Job/API integration
  -> #6 Backtest review integration
  -> #7 README and full verification
```

Rationale:

- Schema comes first because all later services need durable report IDs.
- Data quality comes before research validation because validation can fail fast on bad data.
- Backtest slicing and metrics come before validation orchestration because they define the deterministic evidence.
- Agent integration comes after deterministic reports exist because the LLM consumes evidence instead of creating it.

## What's Working Well

Do not change these parts unless required by the implementation:

- Keep `strategy_idea` candidate generation limited to the existing `ma_cross` whitelist.
- Keep operator approval using the exact stored `backtest_request_payload["payload"]`.
- Keep `backtest_review` parser safety checks for live trading instructions, broker/order wording, profitability guarantees, and generated code.
- Keep paper trading and broker adapter paths out of agent approval and validation jobs.
- Keep `create_all()` support for tests while adding explicit Alembic migration coverage.

## Open Decisions Resolved In This Spec

- Use persisted report tables instead of embedding all validation details into `agent_candidate_reviews`.
- Use weekday expected coverage for v1 instead of exchange holiday calendars.
- Use one validation report per candidate review for v1.
- Require validation before backtest review by default, with explicit `require_validation_report=false` override for legacy local research.
- Treat passed validation as permission for a conservative research recommendation only, never as paper-trading approval.
