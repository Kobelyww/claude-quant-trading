# Quant Trading Platform

Research and paper-trading platform for productized quantitative workflows.

## Current Milestone

This version supports:

- Importing legacy A-share daily data from `legacy/django_app/db.sqlite3`.
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
legacy/django_app/db.sqlite3
```

The importer maps `data_center_symbol` to `instruments` and `data_center_marketdata` to `market_bars`.

## Legacy Reference

The original Claude plugin, scripts, slash commands, skills, and Django demo app live under `legacy/`.

They are kept for migration reference only. New product code lives under `src/quant_trading/`.

## Safety

AI-generated and custom strategies are research artifacts only. Paper trading requires approved, registered strategies. Real broker adapters are outside this milestone.
