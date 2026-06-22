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
http://localhost:8000/workflows/import-legacy
http://localhost:8000/workflows/backtests/ma-cross
http://localhost:8000/workflows/paper/accounts
http://localhost:8000/workflows/paper/runs/ma-cross
http://localhost:8000/workflows/paper/runs/{run_id}/tick
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

## Legacy Data

The first migration source is:

```text
legacy/django_app/db.sqlite3
```

The importer maps `data_center_symbol` to `instruments` and `data_center_marketdata` to `market_bars`.
Existing SQLite databases are not automatically altered by `create_all()`; upgrade old databases with
migrations for new paper tables/columns, especially `portfolio_snapshots.run_id`.

Run the importer through the job task or call `import_legacy_sqlite()` from
`quant_trading.storage.migrate_legacy` in tests and local scripts.

## Legacy Reference

The original Claude plugin, scripts, slash commands, skills, and Django demo app live under `legacy/`.

They are kept for migration reference only. New product code lives under `src/quant_trading/`.

## Roadmap

Next productization stages:

- Add queued execution and progress tracking for long imports/backtests.
- Add authentication before exposing command endpoints beyond local development.
- Add broker adapter interfaces only after paper-trading command contracts are stable.
- Add Alembic migrations for existing databases instead of relying on `create_all()`.

## Safety

This project does not place real broker or exchange orders. Command APIs and dashboard actions
operate on local research and paper-trading state only. AI-generated and custom strategies are
research artifacts only. Paper trading requires approved, registered strategies. Real broker
adapters are outside this milestone.
