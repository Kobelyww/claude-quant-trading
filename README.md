# Quant Trading Platform

Research and paper-trading platform for productized quantitative workflows. This repository is the
new Python package version of the original Django demo app; legacy code is retained under
`legacy/` only as migration reference.

## Current Milestone

This milestone turns the project into a testable service skeleton:

- Importing legacy A-share daily data from `legacy/django_app/db.sqlite3`.
- Storing instruments, market bars, backtest runs, paper snapshots, and risk decisions in SQLAlchemy models.
- Running a portfolio-style moving-average crossover backtest with commission and slippage.
- Running a persistent, risk-gated paper trading account with simulated orders, fills, positions, cash ledger, and snapshots.
- Reading health, instruments, backtests, and paper snapshots through FastAPI.
- Running import and backtest work through job task functions that can be wired to RQ workers.

This version does not place real broker or exchange orders. Paper trading is still a research
simulation with local simulated orders, fills, positions, cash ledger entries, and snapshots.

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
http://localhost:8000/instruments
http://localhost:8000/backtests
http://localhost:8000/paper/accounts
http://localhost:8000/paper/runs
http://localhost:8000/paper/snapshots
```

By default the API service reads `DATABASE_URL`. In Docker Compose it points at PostgreSQL:

```text
postgresql+psycopg://quant:quant@postgres:5432/quant_trading
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

The next productization stage is persistent paper trading:

- Long-lived paper accounts and paper runs.
- Persisted paper orders, fills, positions, and cash ledger entries.
- Idempotent `run_one_tick(run_id, ...)` behavior for already-processed bars.
- Read APIs for paper accounts, runs, positions, cash ledger, orders, fills, snapshots, and risk decisions.

## Safety

AI-generated and custom strategies are research artifacts only. Paper trading requires approved,
registered strategies. Real broker adapters are outside this milestone.
