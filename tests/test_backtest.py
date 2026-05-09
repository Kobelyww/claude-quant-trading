"""回测引擎单元测试"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import unittest

from scripts.backtest_engine import BacktestEngine, BacktestResult
from scripts.strategies import (
    BaseStrategy,
    MACrossStrategy,
    MomentumStrategy,
    MeanReversionStrategy,
    GridStrategy,
)
from scripts.performance import (
    calc_sharpe_ratio,
    calc_max_drawdown,
    calc_win_rate,
    calc_profit_loss_ratio,
    calc_annual_return,
    calc_calmar_ratio,
    performance_report,
)
from scripts.risk import kelly_criterion, position_size, risk_check


def make_synthetic_data(n: int = 252, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing"""
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    returns = np.random.randn(n) * 0.02
    price = 100 * np.cumprod(1 + returns)

    data = pd.DataFrame(
        {
            "open": price * 0.999,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": np.random.randint(10000, 100000, n),
            "symbol": "TEST",
        },
        index=dates,
    )
    return data


class TestBacktestEngine(unittest.TestCase):
    def setUp(self):
        self.data = make_synthetic_data()
        self.engine = BacktestEngine(initial_cash=100000)

    def test_ma_cross_strategy(self):
        strategy = MACrossStrategy(short_window=5, long_window=20)
        result = self.engine.run(self.data, strategy)
        self.assertIsInstance(result, BacktestResult)
        self.assertTrue(len(result.equity_curve) > 0)
        self.assertIn("夏普比率", result.performance)

    def test_momentum_strategy(self):
        strategy = MomentumStrategy(lookback=20)
        result = self.engine.run(self.data, strategy)
        self.assertGreaterEqual(len(result.trades), 0)

    def test_mean_reversion_strategy(self):
        strategy = MeanReversionStrategy(window=20, num_std=2.0)
        result = self.engine.run(self.data, strategy)
        self.assertIsInstance(result.performance, dict)

    def test_grid_strategy(self):
        strategy = GridStrategy(grid_low=80, grid_high=120, grid_step=0.02)
        result = self.engine.run(self.data, strategy)
        self.assertTrue(len(result.performance) > 0)

    def test_compare_strategies(self):
        strategies = [
            MACrossStrategy(short_window=5, long_window=20),
            MACrossStrategy(short_window=10, long_window=50),
            MomentumStrategy(lookback=20),
        ]
        results = self.engine.run_multiple(self.data, strategies)
        self.assertEqual(len(results), 3)

        comp = self.engine.compare(results)
        self.assertEqual(len(comp), 3)

    def test_trending_market(self):
        """Strong uptrend should be profitable for momentum/MA strategies"""
        dates = pd.date_range("2024-01-01", periods=252, freq="B")
        price = 100 * np.cumprod(1 + np.random.randn(252) * 0.01 + 0.001)
        data = pd.DataFrame(
            {
                "open": price * 0.999,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": np.random.randint(10000, 100000, 252),
                "symbol": "UPTREND",
            },
            index=dates,
        )

        strategy = MACrossStrategy(short_window=5, long_window=20)
        result = self.engine.run(data, strategy)
        self.assertTrue(len(result.trades) > 0)


class TestPerformanceMetrics(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.equity = pd.Series(
            100000 * np.cumprod(1 + np.random.randn(252) * 0.01),
            index=pd.date_range("2024-01-01", periods=252, freq="B"),
        )
        self.returns = self.equity.pct_change().dropna()

    def test_sharpe_ratio(self):
        sr = calc_sharpe_ratio(self.returns)
        self.assertIsInstance(sr, float)
        self.assertGreater(sr, -5)
        self.assertLess(sr, 5)

    def test_max_drawdown(self):
        max_dd, dd_start, dd_end = calc_max_drawdown(self.equity)
        self.assertLessEqual(max_dd, 0)
        self.assertGreaterEqual(max_dd, -1)

    def test_calmar_ratio(self):
        cr = calc_calmar_ratio(self.returns, self.equity)
        self.assertIsInstance(cr, float)

    def test_win_rate_empty(self):
        wr = calc_win_rate([])
        self.assertEqual(wr, 0.0)

    def test_win_rate(self):
        trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": -30}]
        wr = calc_win_rate(trades)
        self.assertEqual(wr, 0.5)

    def test_profit_loss_ratio(self):
        trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": -30}]
        plr = calc_profit_loss_ratio(trades)
        self.assertGreater(plr, 1.0)

    def test_annual_return(self):
        ar = calc_annual_return(self.equity)
        self.assertIsInstance(ar, float)

    def test_performance_report(self):
        trades = [
            {"pnl": 100},
            {"pnl": -50},
            {"pnl": 200},
        ]
        report = performance_report(self.equity, trades)
        self.assertIn("夏普比率", report)
        self.assertIn("最大回撤", report)
        self.assertIn("胜率", report)

    def test_flat_equity(self):
        """Flat equity should not produce divide-by-zero errors"""
        flat = pd.Series([100000.0] * 252)
        sr = calc_sharpe_ratio(flat.pct_change().dropna())
        self.assertEqual(sr, 0.0)
        max_dd, _, _ = calc_max_drawdown(flat)
        self.assertEqual(max_dd, 0.0)


class TestRisk(unittest.TestCase):
    def test_kelly_positive(self):
        k = kelly_criterion(0.6, 2.0)
        self.assertGreater(k, 0.0)
        self.assertLessEqual(k, 0.5)

    def test_kelly_negative_edge(self):
        k = kelly_criterion(0.3, 1.0)
        self.assertEqual(k, 0.0)

    def test_kelly_capped(self):
        k = kelly_criterion(0.9, 5.0)
        self.assertLessEqual(k, 0.5)

    def test_position_size(self):
        size = position_size(100000, 50, risk_pct=0.02)
        self.assertGreater(size, 0)

    def test_risk_check_safe(self):
        safe, dd, msg = risk_check(100000, 110000)
        self.assertTrue(safe)

    def test_risk_check_danger(self):
        safe, dd, msg = risk_check(75000, 100000)
        self.assertFalse(safe)


class TestStrategies(unittest.TestCase):
    def setUp(self):
        self.data = make_synthetic_data()

    def test_ma_cross_signal_format(self):
        strategy = MACrossStrategy()
        signals = strategy.generate_signals(self.data)
        self.assertEqual(len(signals), len(self.data))
        self.assertTrue(set(signals.unique()).issubset({-1, 0, 1}))

    def test_momentum_signal_format(self):
        strategy = MomentumStrategy()
        signals = strategy.generate_signals(self.data)
        self.assertEqual(len(signals), len(self.data))

    def test_mean_reversion_signal_format(self):
        strategy = MeanReversionStrategy()
        signals = strategy.generate_signals(self.data)
        self.assertEqual(len(signals), len(self.data))

    def test_grid_signal_format(self):
        strategy = GridStrategy(grid_low=80, grid_high=120, grid_step=0.02)
        signals = strategy.generate_signals(self.data)
        self.assertEqual(len(signals), len(self.data))

    def test_grid_auto_range(self):
        """Grid should auto-detect range when params not provided"""
        strategy = GridStrategy(grid_step=0.02)
        signals = strategy.generate_signals(self.data)
        self.assertEqual(len(signals), len(self.data))

    def test_strategy_repr(self):
        strategy = MACrossStrategy(short_window=10, long_window=30)
        r = repr(strategy)
        self.assertIn("ma_cross", r)


if __name__ == "__main__":
    unittest.main()
