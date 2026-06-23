# Quant Trading Live Job Streaming Design

## Purpose

Stage 8 makes queued work feel operationally live. Stage 7 added durable job events, schedules, and cancellation, but operators still have to refresh the dashboard or poll APIs to see progress. A usable trading operations workbench should show long-running import, sync, backtest, and paper-tick progress as it happens.

This stage adds Server-Sent Events (SSE) streaming for job events and a lightweight dashboard client that can subscribe to the most recent active job. It does not add websocket trading controls, minute bars, tick data, live broker execution, or a distributed message bus.

## Current Context

The platform already has:

- `job_runs` with queued, running, cancel_requested, succeeded, failed, and cancelled state.
- `job_events` with lifecycle and progress events.
- `JobEventRepository.list_for_job(job_run_id)` for ordered event timelines.
- `JobRunRepository.get(job_run_id)` and `list_recent()` for job state.
- `/jobs/{job_run_id}/events` for static event retrieval.
- Token auth middleware protecting job routes when `QUANT_REQUIRE_AUTH=true`.
- A server-rendered dashboard that displays recent job runs, schedules, and events.

The main gap is live visibility. Operators need to see progress events arrive without manual refresh, especially for market-data sync and future longer-running jobs.

## Recommended Architecture

Use a database-backed SSE stream:

- Add `GET /jobs/{job_run_id}/stream`.
- Stream existing `job_events` as SSE `job_event` messages.
- Support `after_event_id` so clients can resume from the last event they processed.
- Poll the database at a short interval and emit only new events.
- Emit heartbeat messages when no new event appears before the heartbeat interval.
- Close the stream after the target job reaches a terminal state and all known events have been sent.

The database remains the source of truth. SSE is a read-side convenience, not an authoritative state store and not a queue transport. This keeps the implementation deterministic in tests and avoids introducing Redis pub/sub, websocket connection registries, or background broadcaster processes.

## API Design

### `GET /jobs/{job_run_id}/stream`

Query parameters:

- `after_event_id`: optional integer, default `0`. Events with `id <= after_event_id` are not sent.
- `poll_interval_seconds`: optional float for tests and local tuning, clamped to a safe range.
- `heartbeat_seconds`: optional float for tests and local tuning, clamped to a safe range.
- `max_idle_seconds`: optional float for tests. In normal operation the stream can remain open until terminal job state or client disconnect.

Response headers:

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`

Event format:

```text
event: job_event
id: 12
data: {"id":12,"job_run_id":1,"event_type":"progress","message":"stored provider bars","progress":90,"payload":{},"created_at":"2026-06-23T10:00:00"}

```

Heartbeat format:

```text
event: heartbeat
data: {}

```

Completion format:

```text
event: stream_end
data: {"job_run_id":1,"status":"succeeded"}

```

Errors:

- Missing job returns `404`.
- Invalid query parameters return FastAPI validation errors.
- Auth behavior matches existing job routes; when token auth is enabled, unauthenticated stream requests return `401`.

## Stream Semantics

The stream loop follows this order:

1. Validate that the job exists.
2. Set `last_event_id` from `after_event_id`.
3. Load events for the job ordered by id.
4. Emit events with `id > last_event_id`; update `last_event_id`.
5. Reload the job status.
6. If status is terminal (`succeeded`, `failed`, `cancelled`) and no unsent events remain, emit `stream_end` and close.
7. If no event was emitted for `heartbeat_seconds`, emit `heartbeat`.
8. Sleep for `poll_interval_seconds` unless the client disconnected.

The stream must not emit duplicate job events in a single connection. A resumed client controls replay with `after_event_id`.

## Dashboard Design

Keep the dashboard server-rendered and operationally dense.

Add a small progressive enhancement:

- Identify the most recent non-terminal job run in the rendered state.
- Add a `data-job-stream-url` attribute with `/jobs/{job_run_id}/stream?after_event_id=<latest_event_id>`.
- Add a compact connection indicator near the Job Events section.
- Use native `EventSource` to listen for `job_event`, `heartbeat`, and `stream_end`.
- On `job_event`, insert a new row at the top of the Job Events table if the event id is new.
- On `stream_end`, mark the indicator as closed and stop listening.

If there is no active job, JavaScript is disabled, or `EventSource` is unavailable, the dashboard remains fully usable as a static page.

## Security And Safety

- Reuse existing token auth middleware.
- Do not include API tokens, provider credentials, raw provider payloads, or exception tracebacks in streamed data.
- Stream only the same sanitized job-event payload already exposed through `/jobs/{job_run_id}/events`.
- Do not add live broker or exchange order paths.
- Do not add websocket command channels or browser-triggered trading actions.

## Testing Strategy

Tests should avoid real Redis, real network providers, and browser-only dependencies.

Cover:

- Streaming an existing job sends ordered `job_event` messages.
- `after_event_id` skips already processed events.
- A terminal job emits `stream_end` after pending events.
- Missing job stream returns `404`.
- Auth middleware protects the stream route when enabled.
- Dashboard renders the stream URL and lightweight client script for an active job.
- Dashboard remains static when no active job exists.
- Existing job event APIs, schedule APIs, dashboard tests, and full test suite still pass.

## Non-Goals

Stage 8 does not include:

- WebSocket APIs.
- Redis pub/sub or external broadcast infrastructure.
- Streaming market ticks, minute bars, or quote updates.
- Browser controls for cancelling jobs or creating schedules.
- High-availability scheduler locking.
- Live broker or exchange execution.
- Multi-user entitlement filtering beyond existing token auth.

## Acceptance Criteria

- Operators can open an SSE stream for a job and receive job events without manual polling.
- Clients can resume from a known event id.
- Streams end cleanly for terminal jobs.
- The dashboard can subscribe to the most recent active job and append new events.
- Existing auth protects the stream endpoint.
- The feature works in tests without Redis, AkShare, yfinance, CCXT, or real network access.
- No live broker or exchange order path is added.
