# Quant Trading Scheduled Operations Design

## Purpose

Stage 7 makes the platform safer to operate over repeated market days. Stage 6 added provider-backed market-data sync through queued jobs, but operators still have to trigger sync manually and cannot inspect detailed job progress or cancel work cleanly.

This stage adds a lightweight operations control plane for scheduled market-data sync, job event timelines, and explicit cancellation semantics. It does not add real broker execution, high-availability distributed scheduling, minute-bar ingestion, or websocket streaming.

## Current Context

The platform already has:

- `job_runs` with queued/running/succeeded/failed lifecycle state.
- Inline and RQ job execution through `submit_job_run()` and `execute_job_run_with_engine()`.
- Provider-backed daily sync through `market_data_sync`.
- `data_sync_runs` as the market-data ingestion audit trail.
- `/jobs`, `/jobs/{job_run_id}`, `/jobs/market-data/sync`, `/data-sync-runs`, and dashboard visibility.

The main product gap is operational control. A usable trading platform needs a repeatable way to schedule daily data refresh, see job state transitions, and stop queued or cooperative running jobs without editing the database.

## Recommended Architecture

Add three focused components:

- **`job_events` audit log** records lifecycle and progress events for every queued job.
- **`job_schedules` schedule registry** stores enabled recurring job definitions, initially for `market_data_sync`.
- **Scheduled operations service** finds due schedules, submits jobs through the existing job service, advances `next_run_at`, records events, and supports cancellation.

The database remains the source of truth. RQ remains the async transport for actual job execution. Stage 7 deliberately uses an explicit scheduler tick function rather than a heavyweight scheduler dependency; deployment can run this tick from a cron, a worker loop, or a future dedicated scheduler service.

## Data Model

### `JobEventORM`

Add `job_events`.

Fields:

- `id`: integer primary key.
- `job_run_id`: integer reference to `job_runs.id`, indexed.
- `event_type`: string, indexed. Supported values:
  - `queued`
  - `enqueued`
  - `running`
  - `progress`
  - `cancel_requested`
  - `cancelled`
  - `succeeded`
  - `failed`
- `message`: short text, default empty string.
- `progress`: optional integer.
- `payload`: JSON text string, default `{}`. Store small operational metadata only.
- `created_at`: datetime, indexed.

No credentials, API tokens, raw provider payloads, or full exception tracebacks are stored.

### `JobScheduleORM`

Add `job_schedules`.

Fields:

- `id`: integer primary key.
- `name`: string, unique, indexed.
- `job_type`: string, indexed. Stage 7 supports `market_data_sync`.
- `request_payload`: JSON text object.
- `schedule_type`: string. Stage 7 supports `interval`.
- `interval_seconds`: integer, minimum 60.
- `enabled`: boolean, default true, indexed.
- `next_run_at`: datetime, indexed.
- `last_run_at`: optional datetime.
- `last_job_run_id`: optional integer reference to `job_runs.id`.
- `created_at`: datetime.
- `updated_at`: datetime.

The schedule registry does not store provider credentials. Market-data providers must use existing local dependency/configuration mechanisms.

## Job Event Behavior

Update existing job lifecycle code to append events:

1. `submit_job_run()` creates a `queued` event after the `job_runs` row is created.
2. RQ enqueue success records `enqueued` with the RQ job id.
3. `execute_job_run_with_engine()` records `running` after marking the job running.
4. Long-running job handlers can record `progress` events. Stage 7 adds this to `market_data_sync` around provider fetch and bar upsert phases.
5. Success records `succeeded` with progress `100`.
6. Failure records `failed` with capped error message.
7. Cancellation requests record `cancel_requested`; final cancellation records `cancelled`.

The `job_runs.progress` field remains the quick summary. `job_events` is the detailed timeline.

## Cancellation Semantics

Add repository/service support for cancellation.

Rules:

- `queued` jobs can be marked `cancelled` immediately before execution starts.
- `running` jobs are marked with status `cancel_requested` and a `cancel_requested` event.
- Job execution checks cancellation before running the payload and at cooperative checkpoints.
- If cancellation is observed before payload execution, the job is marked `cancelled` and no workflow command is run.
- If cancellation is observed during `market_data_sync`, the sync run is marked `failed` with error text `cancelled` and the job is marked `cancelled`.
- Terminal jobs (`succeeded`, `failed`, `cancelled`) cannot be cancelled again.

RQ transport cancellation is best-effort in Stage 7. If an RQ job has not started, a future worker may still need to skip it by checking database state at execution start.

## Schedule Service

Create `quant_trading.jobs.schedules`.

Primary API:

```python
run_due_schedules(
    engine: Engine,
    settings: AppSettings,
    now: datetime,
    queue_factory: Callable[[str], QueueLike],
) -> list[dict[str, Any]]
```

Behavior:

1. Find enabled schedules where `next_run_at <= now`.
2. Submit one job per due schedule through `submit_job_run()`.
3. Store `last_run_at`, `last_job_run_id`, and a new `next_run_at`.
4. Return submitted schedule/job summaries.
5. If one schedule fails validation, record its error in a job event when a job exists, skip that schedule, and continue processing other due schedules.

Stage 7 supports `schedule_type="interval"` only. `next_run_at` advances by `interval_seconds` from the current `next_run_at`, repeatedly if needed until it is after `now`. This prevents a long downtime from submitting a large backlog.

## API Design

New routes use existing token auth middleware.

### Schedules

- `POST /job-schedules`
  - Creates a schedule.
  - Body:

```json
{
  "name": "daily-000001-sync",
  "job_type": "market_data_sync",
  "request_payload": {
    "provider": "akshare",
    "symbol": "000001",
    "start": "2026-01-01",
    "end": "2026-06-23"
  },
  "interval_seconds": 86400,
  "next_run_at": "2026-06-24T09:30:00"
}
```

- `GET /job-schedules`
  - Optional filters: `enabled`, `job_type`, `limit`.

- `GET /job-schedules/{schedule_id}`
  - Returns one schedule or `404`.

- `PATCH /job-schedules/{schedule_id}`
  - Allows updating `enabled`, `request_payload`, `interval_seconds`, and `next_run_at`.

- `POST /job-schedules/run-due`
  - Executes one scheduler tick using current server time unless a test-only `now` value is supplied.
  - This route is operator-only and protected by existing auth.

### Job Control And Events

- `POST /jobs/{job_run_id}/cancel`
  - Requests cancellation and returns the updated job payload.

- `GET /jobs/{job_run_id}/events`
  - Returns the job event timeline ordered by creation time.

Response shape for events:

```json
{
  "id": 1,
  "job_run_id": 12,
  "event_type": "running",
  "message": "job started",
  "progress": 10,
  "payload": {},
  "created_at": "2026-06-23T10:00:00"
}
```

## Dashboard Design

Add two sections:

- **Job Schedules**
  - ID, name, job type, enabled, interval, next run, last run, last job.
- **Job Events**
  - Recent events across jobs: job id, type, message, progress, time.

Keep the dashboard operational and dense. Do not add a form-heavy scheduler UI in Stage 7; operators can use the API to create schedules and use the dashboard to inspect state.

## Error Handling

- Unknown schedule job types are rejected at schedule creation.
- `interval_seconds < 60` is rejected.
- `request_payload` must be a JSON object.
- Invalid `next_run_at` is rejected by API validation.
- Cancelling a missing job returns `404`.
- Cancelling terminal jobs returns the existing terminal job unchanged plus a `409` API response.
- Scheduler tick skips disabled schedules.
- Scheduler tick processes remaining schedules even if one due schedule fails.

## Testing Strategy

Tests should avoid real network and real Redis dependencies.

Cover:

- Alembic migration creates `job_events` and `job_schedules`.
- `JobEventRepository` records and lists events.
- `JobScheduleRepository` creates, updates, filters, and advances interval schedules.
- `submit_job_run()` records queued/enqueued events.
- `execute_job_run_with_engine()` records running/succeeded/failed events.
- `cancel_job_run()` handles queued, running, terminal, and missing jobs.
- `market_data_sync` checks cancellation at cooperative checkpoints with fake providers.
- `run_due_schedules()` submits due schedules and advances `next_run_at` without backlog bursts.
- API coverage for schedules, cancellation, and job events.
- Auth coverage for new routes.
- Dashboard renders schedules and recent events.
- Full test suite and Docker Compose config still pass.

## Non-Goals

Stage 7 does not include:

- Live broker or exchange order execution.
- High-availability distributed scheduler locking.
- APScheduler, Celery Beat, RQ Scheduler, or external scheduler dependencies.
- Cron expression parsing.
- Minute bars, tick data, or websocket streaming.
- Provider fallback routing.
- Multi-user entitlements.

## Acceptance Criteria

- Operators can define enabled interval schedules for market-data sync jobs.
- Operators can run a scheduler tick and see due jobs submitted.
- Due schedules advance `next_run_at` without submitting unbounded backlog.
- Operators can cancel queued jobs and request cancellation for running jobs.
- Job execution records a queryable event timeline.
- Dashboard shows schedules and recent job events.
- New APIs are protected by existing auth.
- No credentials or raw provider payloads are stored.
- No live broker or exchange order path is added.
- Full tests and Docker Compose config pass.
