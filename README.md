# Quant Trading Platform

Research and paper-trading platform for productized quantitative workflows.

## Current Milestone

This version supports:

- Importing legacy A-share daily data from `django_app/db.sqlite3`.
- Storing instruments and market bars in normalized SQLAlchemy models.
- Running a portfolio-style MA cross backtest.
- Running a risk-gated paper trading tick with simulated fills.
- Reading health, instruments, backtests, and paper snapshots through FastAPI.

This version does not place real broker or exchange orders.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/unit tests/integration -q
```

## Local Services

```bash
docker compose up --build
```

API:

```text
http://localhost:8000/health
http://localhost:8000/instruments
http://localhost:8000/backtests
http://localhost:8000/paper/snapshots
```

## Legacy Data

The first migration source is:

```text
django_app/db.sqlite3
```

The importer maps `data_center_symbol` to `instruments` and `data_center_marketdata` to `market_bars`.

## Safety

AI-generated and custom strategies are research artifacts only. Paper trading requires approved, registered strategies. Real broker adapters are outside this milestone.
