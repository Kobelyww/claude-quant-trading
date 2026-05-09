---
description: Fetch historical market data for quantitative analysis
argument-hint: "<symbol> [--start YYYYMMDD] [--end YYYYMMDD] [--market auto|a_stock|us_stock|crypto]"
---

# Fetch Market Data

Pull historical OHLCV data for any supported asset across A-shares, US stocks, and cryptocurrencies.

## Workflow

### Step 1: Parse Arguments

- `symbol`: Required. Stock ticker or crypto pair (e.g., `000001`, `AAPL`, `BTC/USDT`)
- `--start`: Start date (default: 1 year ago)
- `--end`: End date (default: today)
- `--market`: Market type override (default: auto-detect)

### Step 2: Fetch Data

Load the `quant-data` skill and fetch data using `scripts/data_fetcher.py`:

```bash
cd quant-trading && python3 -c "
from scripts.data_fetcher import DataFetcher
fetcher = DataFetcher()
df = fetcher.fetch('<SYMBOL>', start='<START>', end='<END>')
df.to_csv('<SYMBOL>_data.csv')
print(f'Fetched {len(df)} rows, saved to <SYMBOL>_data.csv')
print(df.describe())
"
```

### Step 3: Quick Validate

Show:
- Date range and number of bars
- OHLCV summary statistics
- Any data gaps or quality issues

### Step 4: Save Output

Data saved to `<SYMBOL>_data.csv` in the current working directory, ready for backtesting.

## Example

```
/fetch 000001 --start 20240101 --end 20241231
/fetch AAPL --market us_stock
/fetch BTC/USDT --start 2024-06-01
```
