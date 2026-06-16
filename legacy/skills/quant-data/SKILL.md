---
name: quant-data
description: |
  Multi-market data acquisition for quantitative trading. Fetches historical OHLCV data from A-shares (akshare), US stocks (yfinance), and cryptocurrencies (ccxt/binance) with a unified interface. Auto-detects market type from symbol format.

  **Perfect for:**
  - Pulling historical daily/weekly/monthly bars for backtesting
  - Batch downloading data for multiple symbols
  - Initial data seeding for strategy research
  - Comparing assets across different markets

  **Not ideal for:**
  - Real-time tick data (not supported yet)
  - Fundamental/financial statement data
  - Options or futures data
---

# Quantitative Data Fetcher

## Overview

This skill fetches historical market data for quantitative analysis across three markets: A-shares (China), US stocks, and cryptocurrencies. Data is returned in a unified OHLCV format ready for backtesting and strategy research.

## Tools

- Use `quant-trading/scripts/data_fetcher.py` as the primary data engine.
- Default to using the `DataFetcher` class for all data operations.

## Critical Constraints

**Symbol format matters:**
- A-shares: 6-digit numeric code (e.g., `000001` for 平安银行, `600519` for 贵州茅台)
- US stocks: standard ticker symbol (e.g., `AAPL`, `TSLA`, `MSFT`)
- Crypto: `BTC/USDT`, `ETH/USDT` format (Binance exchange)

**Date format:**
- Accept both `YYYYMMDD` and `YYYY-MM-DD` formats
- Default to 1 year of data if no dates specified

**Data quality:**
- A-shares use 前复权 (forward-adjusted) prices by default
- Crypto data from Binance, max 1000 candles per request
- Always validate returned data has required columns: open, high, low, close, volume

## Workflow

### Step 1: Determine Market

Auto-detect market type from the symbol format. If ambiguous, ask the user to specify.

### Step 2: Fetch Data

Run the data fetcher script:

```bash
cd quant-trading && python3 -c "
from scripts.data_fetcher import DataFetcher
import json

fetcher = DataFetcher()
df = fetcher.fetch('<SYMBOL>', start='<START>', end='<END>')
print(f'Fetched {len(df)} rows from {df.index[0]} to {df.index[-1]}')
print(df.describe())
# Save for later use
df.to_csv('<SYMBOL>_data.csv')
"
```

### Step 3: Quick Validation

Check for:
- Data continuity (no large gaps in dates)
- Minimum data points (>50 bars for meaningful analysis)
- Price range reasonableness
- Volume > 0 on most trading days

### Step 4: Return Summary

Present a concise summary:
- Symbol and market
- Date range and number of bars
- Price range (low-high)
- Average daily volume
- Any data quality issues found

## Guardrails

- **No data fabrication.** If a data source returns empty or errors, report it — do not generate synthetic data.
- **Handle errors gracefully.** Network errors or invalid symbols should produce clear error messages, not crashes.
- **Limit batch size.** When fetching multiple symbols, space requests to avoid rate limiting.
- **Cite the data source** (akshare, yfinance, or ccxt) in all outputs.
