# Quant Trading Queued Runtime Design

## Purpose

Stage 5 turns synchronous operator workflows into observable queued jobs for imports, backtests, and paper ticks. The platform should remain safe for local paper trading while becoming closer to a production service: API requests should return quickly, long-running work should have durable status, and operators should be able to inspect progress and failures from both API and dashboard.

This stage does not add live broker or exchange execution. All commands still operate on local research and paper-trading state.

## Current Context

The platform already has:

- FastAPI routes for health, read APIs, workflow commands, and dashboard actions.
- SQLAlchemy storage models and Alembic migration infrastructure.
- `workflow_runs` for command audit history.
- `quant_trading.jobs.queue.make_queue()` and Docker Compose Redis/RQ worker wiring.
- Synchronous workflow functions for legacy import, MA Cross backtest, paper account creation, paper run creation, and paper tick execution.

The main product gap is that imports, backtests, and paper ticks still block the API process. `workflow_runs` records what happened, but it is not a job queue or progress system.

## Recommended Architecture

Use a database-backed `job_runs` table as the product source of truth, with pluggable executors:

- **Inline executor** for tests and lightweight local development.
- **RQ executor** for Docker/production-like local runs.

`job_runs` records job lifecycle and progress. RQ is an execution transport, not the authoritative status store. This keeps API, dashboard, tests, and operators looking at one durable database model even when the worker process is separate.

`workflow_runs` remains command audit. `job_runs` becomes execution lifecycle.

## Data Model

Add `JobRunORM` mapped to `job_runs`.

Fields:

- `id`: integer primary key.
- `job_type`: string, indexed. Supported values in this stage:
  - `import_legacy`
  - `backtest_ma_cross`
  - `paper_run_tick`
- `status`: string, indexed. Supported values:
  - `queued`
  - `running`
  - `succeeded`
  - `failed`
  - `canceled`
- `progress`: integer percent from `0` to `100`.
- `request_payload`: JSON string.
- `result_payload`: JSON string.
- `error_message`: optional text, sanitized and length-limited.
- `workflow_run_id`: optional integer reference to the audit row created when the job executes.
- `rq_job_id`: optional string for queued RQ jobs.
- `queued_at`, `started_at`, `finished_at`, `created_at`, `updated_at`: datetimes.
- `duration_ms`: optional integer.

The database is the source for status. RQ job ids are diagnostic links only.

## Execution Flow

### Inline mode

Used by tests and default local development:

1. API validates request.
2. API creates `job_runs` row with `queued` and progress `0`.
3. Inline executor immediately marks it `running`.
4. Executor calls the corresponding workflow through the existing workflow audit runner.
5. Executor updates `job_runs` to `succeeded` with progress `100` and result payload, or `failed` with error message.
6. API returns the final job payload.

### RQ mode

Used by Docker/production-like local runs:

1. API validates request.
2. API creates `job_runs` row with `queued` and progress `0`.
3. API enqueues an RQ job containing `database_url` and `job_run_id`.
4. API stores the returned `rq_job_id` and returns the queued job payload.
5. Worker loads the `job_runs` row, marks it `running`, executes the workflow through the audit runner, and persists final state.

RQ mode must never require the API process to execute long-running workflow logic.

## Configuration

Add settings:

- `QUANT_JOB_EXECUTOR`: `inline` or `rq`, default `inline`.
- `REDIS_URL`: default `redis://localhost:6379/0`.

Docker Compose should set `QUANT_JOB_EXECUTOR=rq` for the API and worker services. Local one-process runs can keep the default inline executor.

## API Design

New routes use token auth through existing middleware:

- `POST /jobs/import-legacy`
  - Body: `{ "legacy_db_path": "legacy/django_app/db.sqlite3" }`
  - Creates an `import_legacy` job.
- `POST /jobs/backtests/ma-cross`
  - Body includes `symbol`, `short_window`, `long_window`, `order_size`, `initial_cash`.
  - Creates a `backtest_ma_cross` job.
- `POST /jobs/paper/runs/{run_id}/tick`
  - Creates a `paper_run_tick` job.
- `GET /jobs`
  - Query filters: optional `status`, optional `job_type`, `limit` clamped to `1..100`.
- `GET /jobs/{job_run_id}`
  - Returns one job or `404`.

Job payload shape:

```json
{
  "id": 1,
  "job_type": "backtest_ma_cross",
  "status": "succeeded",
  "progress": 100,
  "request_payload": {},
  "result_payload": {},
  "error_message": null,
  "workflow_run_id": 12,
  "rq_job_id": null,
  "queued_at": "2026-06-23T10:00:00",
  "started_at": "2026-06-23T10:00:01",
  "finished_at": "2026-06-23T10:00:05",
  "duration_ms": 4000,
  "created_at": "2026-06-23T10:00:00",
  "updated_at": "2026-06-23T10:00:05"
}
```

Existing synchronous `/workflows/...` routes remain for now. They preserve backward compatibility and continue to write `workflow_runs`.

## Dashboard Design

Add a `Job Runs` section near `Workflow Runs`.

Columns:

- ID
- Type
- Status
- Progress
- Started
- Duration
- Workflow Run
- Error

Dashboard form actions remain synchronous in this stage unless routed through the new job endpoints later. The dashboard must still display queued jobs created through the API or RQ worker.

## Worker Entrypoint

Add a small worker-facing function:

```python
execute_job_run(database_url: str, job_run_id: int) -> dict
```

It should:

- Load the job row.
- Reject unknown job ids and unsupported job types.
- Mark queued job as running.
- Dispatch to existing workflow functions through the workflow audit runner.
- Store the associated `workflow_run_id` when available.
- Persist result or sanitized error.
- Return JSON-safe job result for RQ diagnostics.

The worker should not contain business strategy logic. It delegates to existing workflow operations.

## Error Handling

- Validation failures in API return `400` or `422` before job creation.
- Unknown job id returns `404` in read API.
- Unknown job type marks job failed when encountered by the worker.
- Workflow `ValueError` and `FileNotFoundError` are captured into `job_runs.error_message` and mark the job failed.
- Error messages are capped at 1000 characters.
- API tokens are not included in request payloads, result payloads, or logs.

## Testing Strategy

Tests should cover:

- `JobRunRepository` lifecycle: create queued, mark running, mark succeeded, mark failed, list filters, get by id.
- Inline executor success and failure for supported job types.
- API job creation and read endpoints with auth enabled and disabled.
- RQ executor enqueue behavior using a fake queue object, without requiring a real Redis server.
- Dashboard rendering of job runs and failed status styling.
- Alembic migration creates `job_runs`.
- Existing workflow, auth, migration, dashboard, and paper tests still pass.

Follow TDD for implementation: write each failing test first, verify failure, then implement the minimal code.

## Non-Goals

This stage does not include:

- Live broker adapters.
- Multi-user permissions.
- Distributed locking.
- Scheduled recurring jobs.
- Job cancellation for already running RQ jobs.
- SSE or websocket live streaming.
- Parameter sweeps or optimization grids.

## Acceptance Criteria

- Operators can create import, MA Cross backtest, and paper tick jobs through `/jobs/...`.
- Operators can list and inspect job status through API.
- Dashboard shows recent job runs with progress and failure context.
- RQ mode enqueues work without running it in the API process.
- Inline mode provides deterministic local/test execution.
- `workflow_runs` remains the audit trail for executed commands.
- `job_runs` remains the lifecycle source of truth for background work.
- Full test suite and Docker Compose config pass after implementation.
