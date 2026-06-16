"""回测结果重新计算 - 对标 financial-services 的 recalc.py"""

import pandas as pd
import numpy as np
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backtest_engine import BacktestEngine
from scripts.strategies import (
    MACrossStrategy,
    MomentumStrategy,
    MeanReversionStrategy,
    GridStrategy,
)
from scripts.visualization import (
    plot_equity_curve,
    plot_monthly_heatmap,
    plot_returns_distribution,
    plot_strategy_comparison,
)

STRATEGY_MAP = {
    "ma_cross": MACrossStrategy,
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "grid": GridStrategy,
}


def main():
    parser = argparse.ArgumentParser(description="Recalculate backtest results")
    parser.add_argument("--data", required=True, help="CSV data file path")
    parser.add_argument("--strategy", required=True, choices=STRATEGY_MAP.keys())
    parser.add_argument("--params", default="{}", help="Strategy params as JSON")
    parser.add_argument("--cash", type=float, default=100000.0)
    parser.add_argument("--output-dir", default=".", help="Output directory")

    args = parser.parse_args()

    data = pd.read_csv(args.data, index_col=0, parse_dates=True)
    params = json.loads(args.params)
    strategy_cls = STRATEGY_MAP[args.strategy]
    strategy = strategy_cls(**params)

    engine = BacktestEngine(initial_cash=args.cash)
    result = engine.run(data, strategy)

    print("=" * 50)
    print(f"Backtest: {data['symbol'].iloc[0]} - {strategy.name}")
    print("=" * 50)
    for k, v in result.performance.items():
        print(f"  {k}: {v}")
    print("=" * 50)
    print(f"Trades: {len([t for t in result.trades if t.get('pnl')])}")
    print(f"Equity curve saved to {args.output_dir}/equity_curve.png")

    plot_equity_curve(
        result.equity_curve,
        title=f"{data['symbol'].iloc[0]} - {strategy.name}",
        output_path=f"{args.output_dir}/equity_curve.png",
    )
    plot_monthly_heatmap(
        result.equity_curve,
        output_path=f"{args.output_dir}/monthly_heatmap.png",
    )
    plot_returns_distribution(
        result.equity_curve,
        output_path=f"{args.output_dir}/returns_dist.png",
    )

    print("Done.")


if __name__ == "__main__":
    main()
