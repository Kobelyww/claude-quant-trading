# Quant Trading Scheduler Leases Design

## Purpose

Stage 9 makes scheduled operations safe enough for multi-instance deployment. Stage 7 added explicit scheduler ticks, but `run_due_schedules()` currently reads due schedules, submits jobs, and only then advances `next_run_at`. If two API or worker instances run the tick at the same time, both can submit the same due schedule.

This stage adds database-backed schedule leases so only one scheduler runner can claim a due schedule at a time. It does not add live broker execution, a long-running scheduler daemon, cron parsing, leader election, Redis locks, or a new queue system.

## Current Context

The platform already has:

- `job_schedules` for interval `market_data_sync` jobs.
- `run_due_schedules()` as an explicit scheduler tick.
- `job_runs` and `job_events` for durable job lifecycle tracking.
- Inline and RQ job executors.
- Alembic migrations and `create_all()` test schema support.

The risk is in the claim boundary. A due schedule is visible to every scheduler runner until one runner has submitted a job and marked the schedule submitted. That gap can create duplicate jobs under concurrent ticks.

## Recommended Architecture

Use the SQL database as the schedule lease authority.

Add nullable lease columns to `job_schedules`:

- `locked_until`: datetime, indexed. A future value means the schedule is actively claimed.
- `locked_by`: string scheduler identity for diagnostics.
- `lock_acquired_at`: datetime for diagnostics.

Add repository methods that acquire a lease with a single conditional `UPDATE`:

```text
UPDATE job_schedules
SET locked_until = :lease_until,
    locked_by = :scheduler_id,
    lock_acquired_at = :now,
    updated_at = :now
WHERE id = :schedule_id
  AND enabled = true
  AND next_run_at <= :now
  AND (locked_until IS NULL OR locked_until <= :now)
```

Only a runner that updates one row owns the schedule. Other runners skip it. This works in SQLite tests and maps cleanly to PostgreSQL production deployments.

## Runtime Behavior

`run_due_schedules()` keeps its existing public API and gains keyword-only options:

```python
run_due_schedules(
    engine,
    settings,
    now,
    queue_factory,
    *,
    scheduler_id=None,
    lease_seconds=300,
)
```

Behavior:

1. Build a stable scheduler identity when `scheduler_id` is not supplied.
2. List due schedules that are not actively leased.
3. For each due schedule, attempt the atomic lease update.
4. If the lease is not acquired, skip that schedule.
5. After acquiring the lease, load the schedule payload and compute the advanced `next_run_at`.
6. Submit the job through the existing job service.
7. On success, store `last_run_at`, `last_job_run_id`, advanced `next_run_at`, and clear lease fields.
8. If submission raises an exception, clear the lease and re-raise so API callers see the failure.

The lease protects the scheduler submission window, not the whole job runtime. Production-like multi-instance deployments should run scheduled jobs with the queued executor (`QUANT_JOB_EXECUTOR=rq`), so job execution happens after the schedule occurrence has been claimed and submitted.

## Expired Leases

Expired leases are treated as available. This covers scheduler crashes between claim and release. A future tick can claim the schedule again after `locked_until <= now`.

The default lease is 300 seconds. Tests pass explicit small leases where needed. Operators can tune `lease_seconds` when wiring a dedicated scheduler loop later.

## API And Dashboard Impact

No new endpoint is required.

`POST /job-schedules/run-due` continues to run one explicit scheduler tick. It uses the default lease behavior.

Schedule payloads returned by the API include:

- `locked_until`
- `locked_by`
- `lock_acquired_at`

The dashboard schedule table adds a compact `Lease` column. It shows the scheduler identity and expiry for actively leased schedules, or an empty value when no active lease is present.

## Error Handling

- `lease_seconds < 1` raises `ValueError`.
- Disabled schedules cannot be acquired.
- Schedules whose `next_run_at` is in the future cannot be acquired.
- Actively leased schedules cannot be acquired by another runner.
- Expired leases can be reacquired.
- If job submission fails after lease acquisition, the lease is cleared and the error propagates.

The implementation must not hide submit failures. Silent failures make operational state harder to trust.

## Testing Strategy

Tests must not use real Redis, AkShare, brokers, or network access.

Cover:

- ORM and Alembic migration include the three lease columns.
- Repository lease acquisition succeeds for due unlocked schedules.
- Repository acquisition fails for actively leased schedules.
- Repository acquisition succeeds after lease expiry.
- `run_due_schedules()` submits a due schedule only once when a competing runner already holds a lease.
- `run_due_schedules()` releases the lease and advances the schedule after successful submit.
- `run_due_schedules()` releases the lease when job submission fails.
- Schedule API responses expose lease fields.
- Dashboard renders lease state without changing schedule control flow.
- Existing scheduled operations, job event streaming, auth, migration, and full tests still pass.

## Non-Goals

Stage 9 does not include:

- Live broker or exchange order execution.
- Redis, etcd, PostgreSQL advisory locks, or leader election.
- A daemonized scheduler process.
- Cron expressions.
- A schedule occurrence table.
- Exactly-once broker order semantics.

## Success Criteria

- Concurrent scheduler ticks cannot both submit the same actively leased due schedule.
- Expired leases recover without manual database edits.
- Operators can see lease state through API/dashboard diagnostics.
- Existing schedule APIs remain backward compatible.
- Full test suite passes with SQLite-based tests and Docker Compose config remains valid.
