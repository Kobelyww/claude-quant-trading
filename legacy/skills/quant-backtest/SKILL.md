---
name: quant-backtest
description: |
  Event-driven backtesting engine for quantitative trading strategies. Evaluates any strategy against historical data, computes professional performance metrics (Sharpe ratio, max drawdown, Calmar ratio, win rate, profit-loss ratio), and generates publication-quality charts.

  **Perfect for:**
  - Evaluating a trading strategy against historical data
  - Comparing multiple strategies on the same asset
  - Generating performance tear sheets with charts
  - Iterative strategy parameter optimization

  **Not ideal for:**
  - Live/paper trading (this is backtest-only)
  - High-frequency strategies (not tick-level)
  - Multi-asset portfolio optimization
---

# Quantitative Backtest Engine

## Overview

This skill runs professional-grade backtests on trading strategies. It uses an event-driven architecture that simulates realistic order execution with configurable commission and slippage. Output includes a complete performance tear sheet and four chart types.

## Tools

- `quant-trading/scripts/backtest_engine.py` — the core event-driven backtesting loop
- `quant-trading/scripts/performance.py` — all performance metrics
- `quant-trading/scripts/visualization.py` — chart generation (equity curve, drawdown, heatmap, returns distribution)
- `quant-trading/scripts/strategies/` — built-in strategy library

## Critical Constraints

**Data Requirements:**
- Input data MUST have columns: open, high, low, close, volume
- Minimum 50 data points for meaningful metrics
- Use adjusted prices (前复权) for A-shares

**Engine Parameters:**
- Default initial capital: 100,000 CNY/USD
- Default commission: 0.03% (万三)
- Default slippage: 0.1%
- No short selling in default mode (shares >= 0 only)

**Strategy Protocol:**
- Every strategy must implement `generate_signals(data) -> pd.Series`
- Signal values: 1 (buy), -1 (sell), 0 (hold)
- Strategies can have configurable parameters

## Workflow

### Step 1: Prepare Data

Ensure data is loaded and validated. If no data available, use the `quant-data` skill first.

### Step 2: Select Strategy

Choose from built-in strategies or use parameters to customize:

| Strategy | Key Params | Best For |
|----------|-----------|----------|
| `ma_cross` | short_window, long_window | Trend following |
| `momentum` | lookback, top_k | Strength continuation |
| `mean_reversion` | window, num_std | Range-bound markets |
| `grid` | grid_low, grid_high, grid_step | Sideways/volatile |

### Step 3: Run Backtest

```bash
cd quant-trading && python3 -c "
import pandas as pd
from scripts.backtest_engine import BacktestEngine
from scripts.strategies import MACrossStrategy

data = pd.read_csv('<DATA_FILE>', index_col=0, parse_dates=True)
strategy = MACrossStrategy(short_window=5, long_window=20)
engine = BacktestEngine(initial_cash=100000, commission=0.0003)
result = engine.run(data, strategy)

for k, v in result.performance.items():
    print(f'{k}: {v}')
"
```

### Step 4: Generate Charts

```bash
cd quant-trading && python3 -c "
from scripts.visualization import plot_equity_curve, plot_monthly_heatmap, plot_returns_distribution

plot_equity_curve(result.equity_curve, title='<SYMBOL> - <STRATEGY>')
plot_monthly_heatmap(result.equity_curve)
plot_returns_distribution(result.equity_curve)
"
```

### Step 5: Deliver Tear Sheet

Present a comprehensive tear sheet:
1. **Performance table** — all metrics in one view
2. **Equity curve chart** — with drawdown subplot
3. **Monthly returns heatmap** — seasonal pattern analysis
4. **Returns distribution** — with mean and normality check

## Guardrails

- **No look-ahead bias.** The engine processes data sequentially by date index.
- **Always include commission and slippage** in results. Never report gross returns as net.
- **Flag insufficient data.** Warn if < 50 bars or < 5 trades generated.
- **Never overfit.** If running parameter sweeps, remind the user about overfitting risk.
- **Risk-free rate** defaults to 3% for Sharpe ratio calculation.
