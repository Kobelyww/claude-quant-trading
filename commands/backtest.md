---
description: Run backtest for a trading strategy on historical data
argument-hint: "<strategy> --symbol <symbol> [--start YYYYMMDD] [--end YYYYMMDD] [--cash 100000] [--params k=v,...]"
---

# Run Strategy Backtest

Evaluate a trading strategy against historical data with full performance metrics and charts.

## Workflow

### Step 1: Load Data

If data file `<SYMBOL>_data.csv` exists, use it. Otherwise, fetch data first using `/fetch`.

### Step 2: Select Strategy & Parameters

Available built-in strategies:

| Strategy | Params | Description |
|----------|--------|-------------|
| `ma_cross` | short_window=5, long_window=20 | Golden cross / dead cross |
| `momentum` | lookback=20, top_k=5 | Price momentum ranking |
| `mean_reversion` | window=20, num_std=2.0 | Bollinger band reversion |
| `grid` | grid_low, grid_high, grid_step=0.02 | Grid trading |

Custom params: `--params short_window=10,long_window=30`

### Step 3: Run Backtest

Load the `quant-backtest` skill and execute:

```bash
cd quant-trading && python3 -c "
import pandas as pd
from scripts.backtest_engine import BacktestEngine
from scripts.strategies import MACrossStrategy, MomentumStrategy, MeanReversionStrategy, GridStrategy
from scripts.visualization import plot_equity_curve, plot_monthly_heatmap, plot_returns_distribution

data = pd.read_csv('<SYMBOL>_data.csv', index_col=0, parse_dates=True)
strategy = <STRATEGY_CLASS>(**<PARAMS>)
engine = BacktestEngine(initial_cash=<CASH>)
result = engine.run(data, strategy)

for k, v in result.performance.items():
    print(f'{k}: {v}')

plot_equity_curve(result.equity_curve, title='<SYMBOL> - <STRATEGY>')
plot_monthly_heatmap(result.equity_curve)
plot_returns_distribution(result.equity_curve)
print('Charts saved: equity_curve.png, monthly_heatmap.png, returns_dist.png')
"
```

### Step 4: Present Results

Deliver a complete tear sheet:
1. **Performance table** with all key metrics
2. **Equity curve + drawdown chart**
3. **Monthly returns heatmap**
4. **Trade list** (entry/exit dates, prices, PnL per trade)

### Step 5: Compare (Optional)

To compare multiple strategies on the same data:

```bash
cd quant-trading && python3 -c "
import pandas as pd
from scripts.backtest_engine import BacktestEngine
from scripts.strategies import MACrossStrategy, MeanReversionStrategy
from scripts.visualization import plot_strategy_comparison

data = pd.read_csv('<SYMBOL>_data.csv', index_col=0, parse_dates=True)
engine = BacktestEngine()

results = engine.run_multiple(data, [
    MACrossStrategy(short_window=5, long_window=20),
    MACrossStrategy(short_window=10, long_window=50),
    MeanReversionStrategy(window=20, num_std=2.0),
])
print(engine.compare(results))
plot_strategy_comparison({name: r.equity_curve for name, r in results.items()})
"
```

## Example

```
/backtest ma_cross --symbol 000001 --start 2024-01-01 --params short_window=10,long_window=30
/backtest mean_reversion --symbol AAPL --cash 50000
/backtest momentum --symbol BTC/USDT --params lookback=14
```
