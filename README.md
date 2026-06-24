# Quant Trading Platform

Research and paper-trading platform for productized quantitative workflows. This repository is the
new Python package version of the original Django demo app; legacy code is retained under
`legacy/` only as migration reference.

## Current Milestone

This milestone turns the project into a testable operations workbench:

- Importing legacy A-share daily data from `legacy/django_app/db.sqlite3`.
- Storing instruments, market bars, backtest runs, paper snapshots, and risk decisions in SQLAlchemy models.
- Running a portfolio-style moving-average crossover backtest with commission and slippage.
- Running a persistent, risk-gated paper trading account with simulated orders, fills, positions, cash ledger, and snapshots.
- Reading health, instruments, backtests, and paper snapshots through FastAPI.
- Running the operations workbench through command APIs and a server-rendered dashboard.
- Protecting dashboard, read APIs, and workflow commands with optional token auth.
- Migrating runtime schema with Alembic.
- Recording workflow command audit history in `workflow_runs`.
- Tracking queued import, backtest, and paper tick execution lifecycle in `job_runs`.
- Syncing provider-backed daily market data with audit history in `data_sync_runs`.
- Scheduling recurring market-data sync jobs with explicit job event timelines and cancellation controls.
- Completing the local loop: import legacy data -> run MA Cross backtest -> create paper account/run -> trigger paper tick -> inspect results.

This project does not place real broker or exchange orders. Command APIs and dashboard actions
operate on local research and paper-trading state only.

## Project Layout

```text
src/quant_trading/
  api/          FastAPI app and read-only status routes
  backtest/     event-style backtest engine
  core/         domain models, enums, and shared errors
  data/         provider interfaces and validation helpers
  execution/    simulated commission, slippage, and broker fills
  jobs/         import and backtest task functions
  paper/        risk-gated paper tick engine
  portfolio/    accounting and performance metrics
  risk/         reusable risk engine and rules
  storage/      SQLAlchemy models, sessions, and legacy importer
  strategy/     strategy base class, registry, and MA cross strategy
  workflows/    synchronous operator workflows and command audit runner
```

## Requirements

- Python 3.11+
- Docker and Docker Compose for PostgreSQL, Redis, API, and worker services
- Optional data integrations via `.[data]` for AkShare, yfinance, and CCXT

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q
docker compose config
```

Useful narrower test runs:

```bash
python -m pytest tests/unit -q
python -m pytest tests/integration -q
```

## Local Services

```bash
docker compose up --build
```

API endpoints:

```text
http://localhost:8000/health
http://localhost:8000/dashboard
http://localhost:8000/instruments
http://localhost:8000/backtests
http://localhost:8000/paper/accounts
http://localhost:8000/paper/runs
http://localhost:8000/paper/snapshots
http://localhost:8000/agent-runs
http://localhost:8000/agent-runs/{agent_run_id}
http://localhost:8000/workflows/import-legacy
http://localhost:8000/workflows/backtests/ma-cross
http://localhost:8000/workflows/paper/accounts
http://localhost:8000/workflows/paper/runs/ma-cross
http://localhost:8000/workflows/paper/runs/{run_id}/tick
http://localhost:8000/workflows/runs
http://localhost:8000/jobs
http://localhost:8000/jobs/{job_run_id}
http://localhost:8000/jobs/{job_run_id}/cancel
http://localhost:8000/jobs/{job_run_id}/events
http://localhost:8000/jobs/{job_run_id}/stream
http://localhost:8000/jobs/import-legacy
http://localhost:8000/jobs/backtests/ma-cross
http://localhost:8000/jobs/paper/runs/{run_id}/tick
http://localhost:8000/jobs/market-data/sync
http://localhost:8000/jobs/agents/market-analysis
http://localhost:8000/jobs/agents/strategy-idea
http://localhost:8000/job-schedules
http://localhost:8000/job-schedules/run-due
http://localhost:8000/job-schedules/{schedule_id}
http://localhost:8000/data-sync-runs
http://localhost:8000/data-sync-runs/{sync_run_id}
```

By default the API service reads `DATABASE_URL`. In Docker Compose it points at PostgreSQL:

```text
postgresql+psycopg://quant:quant@postgres:5432/quant_trading
```

## Run The Workbench

Start the API locally:

```bash
PYTHONPATH=src python -m uvicorn --factory quant_trading.api.main:create_app --host 127.0.0.1 --port 8000
```

Open the dashboard:

```text
http://127.0.0.1:8000/dashboard
```

The local workflow is:

```text
import legacy data -> run MA Cross backtest -> create paper account -> create MA Cross paper run -> run one paper tick -> inspect results
```

The command APIs are synchronous and intended for local research and paper trading only.

Import legacy data:

```bash
curl -X POST http://127.0.0.1:8000/workflows/import-legacy \
  -H "Content-Type: application/json" \
  -d '{"legacy_db_path":"legacy/django_app/db.sqlite3"}'
```

Run a MA Cross backtest:

```bash
curl -X POST http://127.0.0.1:8000/workflows/backtests/ma-cross \
  -H "Content-Type: application/json" \
  -d '{"symbol":"000001","short_window":5,"long_window":20,"order_size":100,"initial_cash":"100000"}'
```

Create a paper account:

```bash
curl -X POST http://127.0.0.1:8000/workflows/paper/accounts \
  -H "Content-Type: application/json" \
  -d '{"name":"Local Paper","initial_cash":"100000","base_currency":"CNY"}'
```

Create a MA Cross paper run:

```bash
curl -X POST http://127.0.0.1:8000/workflows/paper/runs/ma-cross \
  -H "Content-Type: application/json" \
  -d '{"account_id":1,"symbol":"000001","short_window":5,"long_window":20,"order_size":100,"max_order_value":"100000"}'
```

Run one paper tick:

```bash
curl -X POST http://127.0.0.1:8000/workflows/paper/runs/1/tick
```

## Production Runtime And Safety MVP

Stage 4 hardens the local operations workbench for protected paper-trading use. It still does not place real broker orders.

| Variable | Default | Purpose |
| --- | --- | --- |
| `QUANT_APP_ENV` | `local` | Environment label shown in the dashboard. |
| `DATABASE_URL` | `sqlite+pysqlite:///quant_trading.db` | SQLAlchemy database URL used by the API and Alembic. |
| `QUANT_REQUIRE_AUTH` | `false` | Enables token protection for dashboard, read APIs, and workflow commands. |
| `QUANT_API_TOKEN` | empty | Required when `QUANT_REQUIRE_AUTH=true`. |
| `QUANT_AUTH_HEADER` | `Authorization` | Optional custom header name. `Authorization: Bearer ...` and `X-API-Token` are always supported. |
| `QUANT_PUBLIC_ROUTES` | `/health` | Comma-separated public paths. |

Protected local run:

```bash
QUANT_REQUIRE_AUTH=true QUANT_API_TOKEN=local-token \
PYTHONPATH=src python -m uvicorn --factory quant_trading.api.main:create_app \
  --host 127.0.0.1 --port 8000
```

Authenticated examples:

```bash
curl -H "Authorization: Bearer local-token" http://127.0.0.1:8000/dashboard
curl -H "X-API-Token: local-token" http://127.0.0.1:8000/workflows/runs
```

Schema migration:

```bash
DATABASE_URL=sqlite+pysqlite:///quant_trading.db PYTHONPATH=src alembic upgrade head
```

`create_all()` remains useful for tests and quick local experiments. Production-like local runs should use Alembic so schema state is explicit. Older SQLite files created before this migration stage may need backup and recreation or a manual migration.

Workflow command APIs and dashboard actions write audit rows to `workflow_runs`.

Tracked commands:

- `import_legacy`
- `backtest_ma_cross`
- `paper_create_account`
- `paper_start_ma_cross_run`
- `paper_run_tick`

Read audit history:

```bash
curl -H "Authorization: Bearer local-token" http://127.0.0.1:8000/workflows/runs
curl -H "Authorization: Bearer local-token" http://127.0.0.1:8000/workflows/runs/1
```

Audit rows include status, summarized request payload, result payload, error message, created object reference, start time, finish time, and duration. API tokens are never stored in workflow payloads.

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

`job_runs` records queued/running/cancel_requested/succeeded/failed/cancelled status, progress, result payload, error message, optional RQ job id, and the linked `workflow_run_id`.

Docker Compose sets `QUANT_JOB_EXECUTOR=rq` so API requests enqueue jobs and the worker executes them. This still does not place broker or exchange orders.

## Scheduled Operations And Job Control

Stage 7 adds an operator control plane around queued jobs:

- `POST /job-schedules` creates an enabled interval schedule for `market_data_sync`.
- `GET /job-schedules` lists configured schedules.
- `PATCH /job-schedules/{schedule_id}` enables, disables, or changes a schedule.
- `POST /job-schedules/run-due` runs one explicit scheduler tick.
- `POST /jobs/{job_run_id}/cancel` cancels queued jobs or requests cooperative cancellation for running jobs.
- `GET /jobs/{job_run_id}/events` returns the lifecycle timeline for a job.

Create a daily market-data sync schedule:

```bash
curl -X POST http://127.0.0.1:8000/job-schedules \
  -H "Content-Type: application/json" \
  -d '{"name":"daily-000001-sync","job_type":"market_data_sync","request_payload":{"provider":"akshare","symbol":"000001"},"interval_seconds":86400,"next_run_at":"2026-06-24T09:30:00"}'
```

Run one scheduler tick:

```bash
curl -X POST http://127.0.0.1:8000/job-schedules/run-due \
  -H "Content-Type: application/json" \
  -d '{}'
```

Inspect or cancel a job:

```bash
curl http://127.0.0.1:8000/jobs/1/events
curl -X POST http://127.0.0.1:8000/jobs/1/cancel
```

The scheduler stores only job configuration and operational metadata. It does not store provider credentials, does not place real broker orders, and does not add live exchange execution.

Scheduler ticks use database-backed leases on `job_schedules` (`locked_until`, `locked_by`, and `lock_acquired_at`) so multiple scheduler runners do not submit the same due schedule at the same time. Expired leases are reclaimable on a later tick, which lets the system recover from a scheduler process crash between claim and release.

For production-like deployments, run scheduled operations through the queued executor (`QUANT_JOB_EXECUTOR=rq`). The lease protects schedule submission; job execution remains handled by the worker.

## Live Job Progress Streaming

Stage 8 adds an SSE stream for job-event timelines:

- `GET /jobs/{job_run_id}/stream` streams `job_event`, `heartbeat`, and `stream_end` messages.
- `after_event_id` lets clients resume from the last event they processed.
- The dashboard automatically subscribes to the most recent active job when browser `EventSource` is available.

Example:

```bash
curl -N "http://127.0.0.1:8000/jobs/1/stream?after_event_id=0"
```

The stream is a read-side operational view over `job_events`. It does not add websocket command channels, broker execution, market tick streaming, or provider credential storage.

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

The sync path stores normalized daily bars idempotently and records provider, symbol, range,
status, imported bar count, linked job id, and capped error text. Tests use fake providers;
real local AkShare sync requires installing the optional `.[data]` dependencies. This still does
not place broker or exchange orders.

## Quant Agent

Quant Agent adds audited research agents for market analysis and strategy idea structuring.
Agents run through the existing job runtime and store business-level audit rows in `agent_runs`.

Strategy idea jobs now validate parsed LLM specs as research candidates. V2 supports only the
existing `ma_cross` template and produces a suggested `backtest_ma_cross` request payload when the
spec is complete, safe, and mapped to the whitelist. The request payload is a suggestion only:
operators must submit any backtest explicitly through `/jobs/backtests/ma-cross` or
`/workflows/backtests/ma-cross`.

Create a market analysis job:

```bash
curl -X POST http://127.0.0.1:8000/jobs/agents/market-analysis \
  -H "Content-Type: application/json" \
  -d '{"symbol":"000001","lookback_bars":252,"mode":"overview"}'
```

Create a strategy idea job:

```bash
curl -X POST http://127.0.0.1:8000/jobs/agents/strategy-idea \
  -H "Content-Type: application/json" \
  -d '{"idea":"Use moving-average pullbacks to structure a long-only trend research strategy.","symbol":"000001"}'
```

When validation passes, the job result includes `validation_status="passed"`,
`candidate_payload.strategy_name="ma_cross"`, and a `backtest_request_payload` shaped for the
existing MA Cross backtest job. When validation fails or needs review, candidate and backtest
request payloads are `null` while the agent run remains auditable.

Inspect agent runs:

```bash
curl http://127.0.0.1:8000/agent-runs
curl http://127.0.0.1:8000/agent-runs/1
```

Agent jobs require:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | empty | Required for real LLM-backed agent jobs. |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com` | DeepSeek-compatible API base URL. |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | Model name used by the agent LLM client. |
| `QUANT_AGENT_PROMPT_MAX_CHARS` | `8000` | Maximum prompt characters sent by agent services. |
| `QUANT_AGENT_RESULT_MAX_CHARS` | `12000` | Maximum LLM result characters persisted by agent services. |

Agent outputs are research-only. They do not place orders, call broker adapters, approve strategies,
execute generated code, start paper runs, submit backtests automatically, or provide buy/sell
instructions. Strategy-code generation and automatic trading are intentionally outside this
milestone. Candidate payloads always require human approval.

## Job Tasks

The current task functions live in `quant_trading.jobs.tasks`:

```python
from quant_trading.jobs.tasks import import_legacy_data_task, run_ma_cross_backtest_task

import_legacy_data_task(
    legacy_db_path="legacy/django_app/db.sqlite3",
    database_url="sqlite+pysqlite:///quant_trading.db",
)

run_ma_cross_backtest_task(
    database_url="sqlite+pysqlite:///quant_trading.db",
    symbol="000001",
)
```

## Strategy And Risk Flow

- Strategies produce `OrderIntent` objects from bar history and portfolio state.
- The risk engine evaluates each intent through explicit rules such as strategy approval,
  market data presence, price sanity, and max order value.
- The simulator applies slippage and commission before portfolio accounting accepts or rejects
  the fill.
- Accounting errors such as insufficient cash are surfaced instead of silently producing invalid
  equity.

## Broker Adapter Safety Boundary

Stage 10 adds a broker adapter contract for future live integrations, but this repository still does not place real broker or exchange orders.

Safety defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `QUANT_TRADING_ENABLED` | `false` | Global kill-switch. Future live-capable adapters must refuse submission unless this is true. |
| `QUANT_BROKER_MODE` | `simulated` | Broker mode. Stage 10 supports `simulated` and `dry_run`; live mode is intentionally unavailable. |

Available adapters:

- `SimulatedBrokerAdapter` wraps the existing simulated broker and creates deterministic simulated fills for backtests and paper trading.
- `DryRunBrokerAdapter` records would-submit order requests and returns accepted dry-run results without fills or external calls.

Broker submissions from paper trading are persisted to `broker_order_events`. Each row stores normalized request/result metadata such as client order id, broker order id, mode, status, accepted flag, and a capped message. The audit payload intentionally excludes credentials, API tokens, and raw unbounded broker responses.

The adapter boundary is preparation for real market integration, not a broker integration itself. Real broker adapters require separate credentials handling, account synchronization, live order status reconciliation, kill-switch tests, and explicit operator approval.

## Legacy Data

The first migration source is:

```text
legacy/django_app/db.sqlite3
```

The importer maps `data_center_symbol` to `instruments` and `data_center_marketdata` to `market_bars`.
Existing SQLite databases are not automatically altered by `create_all()`; upgrade old databases with
migrations for new runtime tables and paper tables/columns, especially `workflow_runs` and
`portfolio_snapshots.run_id`.

Run the importer through the job task or call `import_legacy_sqlite()` from
`quant_trading.storage.migrate_legacy` in tests and local scripts.

## Legacy Reference

The original Claude plugin, scripts, slash commands, skills, and Django demo app live under `legacy/`.

They are kept for migration reference only. New product code lives under `src/quant_trading/`.

## Roadmap

Next productization stages:

- Add broker adapter interfaces only after paper-trading command contracts are stable.
- Add operator controls for broker adapter dry runs and kill-switches.
- Add multi-user authorization before exposing this as a public service.
- Add incremental migrations for legacy hand-created SQLite databases.

## Safety

This project does not place real broker or exchange orders. Command APIs and dashboard actions
operate on local research and paper-trading state only. AI-generated and custom strategies are
research artifacts only. Paper trading requires approved, registered strategies. Real broker
adapters are outside this milestone.
