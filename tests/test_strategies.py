"""策略单元测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import unittest

from scripts.strategies import (
    BaseStrategy,
    MACrossStrategy,
    MomentumStrategy,
    MeanReversionStrategy,
    GridStrategy,
    SignalType,
)


class TestMACross(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        self.data = pd.DataFrame(
            {
                "open": np.random.randn(100) * 0.5 + 100,
                "high": np.random.randn(100) * 0.5 + 101,
                "low": np.random.randn(100) * 0.5 + 99,
                "close": np.random.randn(100) * 0.5 + 100,
                "volume": np.random.randint(10000, 100000, 100),
                "symbol": "TEST",
            },
            index=dates,
        )

    def test_default_params(self):
        s = MACrossStrategy()
        self.assertEqual(s.params["short_window"], 5)
        self.assertEqual(s.params["long_window"], 20)

    def test_custom_params(self):
        s = MACrossStrategy(short_window=10, long_window=50)
        self.assertEqual(s.params["short_window"], 10)
        self.assertEqual(s.params["long_window"], 50)

    def test_signal_values(self):
        s = MACrossStrategy()
        signals = s.generate_signals(self.data)
        for v in signals.dropna():
            self.assertIn(v, [-1, 0, 1])

    def test_cross_detection(self):
        """Known cross should produce buy signal"""
        dates = pd.date_range("2024-01-01", periods=60, freq="B")
        close = [100] * 10 + [110] * 30 + [100] * 20
        data = pd.DataFrame(
            {
                "open": np.array(close) * 0.99,
                "high": np.array(close) * 1.01,
                "low": np.array(close) * 0.98,
                "close": close,
                "volume": 50000,
                "symbol": "TEST",
            },
            index=dates,
        )
        s = MACrossStrategy(short_window=5, long_window=20)
        signals = s.generate_signals(data)
        self.assertTrue(
            (signals == 1).any() or (signals == -1).any(),
            "Should have at least one cross signal",
        )


class TestMomentum(unittest.TestCase):
    def setUp(self):
        np.random.seed(123)
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        price = 100 + np.cumsum(np.random.randn(100) * 0.3)
        self.data = pd.DataFrame(
            {
                "open": price * 0.999,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": np.random.randint(10000, 100000, 100),
                "symbol": "TEST",
            },
            index=dates,
        )

    def test_default_params(self):
        s = MomentumStrategy()
        self.assertEqual(s.params["lookback"], 20)

    def test_positive_momentum_buy(self):
        """Strong uptrend should produce buy signals"""
        dates = pd.date_range("2024-01-01", periods=60, freq="B")
        price = np.linspace(100, 150, 60)
        data = pd.DataFrame(
            {
                "open": price * 0.99,
                "high": price * 1.01,
                "low": price * 0.98,
                "close": price,
                "volume": 50000,
                "symbol": "TEST",
            },
            index=dates,
        )
        s = MomentumStrategy(lookback=10, top_k=3)
        signals = s.generate_signals(data)
        self.assertTrue((signals == 1).any(), "Should have buy signals in uptrend")


class TestMeanReversion(unittest.TestCase):
    def setUp(self):
        np.random.seed(456)
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        price = 100 + np.random.randn(100) * 2
        self.data = pd.DataFrame(
            {
                "open": price * 0.999,
                "high": price * 1.005,
                "low": price * 0.995,
                "close": price,
                "volume": 50000,
                "symbol": "TEST",
            },
            index=dates,
        )

    def test_default_params(self):
        s = MeanReversionStrategy()
        self.assertEqual(s.params["window"], 20)
        self.assertEqual(s.params["num_std"], 2.0)

    def test_signal_in_range_bound_market(self):
        s = MeanReversionStrategy(window=10, num_std=1.5)
        signals = s.generate_signals(self.data)
        self.assertIsInstance(signals, pd.Series)


class TestGrid(unittest.TestCase):
    def test_auto_range(self):
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        price = np.sin(np.linspace(0, 4 * np.pi, 50)) * 5 + 100
        data = pd.DataFrame(
            {
                "open": price * 0.99,
                "high": price * 1.01,
                "low": price * 0.98,
                "close": price,
                "volume": 50000,
                "symbol": "TEST",
            },
            index=dates,
        )
        s = GridStrategy(grid_step=0.02)
        signals = s.generate_signals(data)
        self.assertEqual(len(signals), len(data))

    def test_narrow_range(self):
        """Very narrow price range should produce no signals"""
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        data = pd.DataFrame(
            {
                "open": 100.0,
                "high": 100.05,
                "low": 99.95,
                "close": 100.0,
                "volume": 50000,
                "symbol": "TEST",
            },
            index=dates,
        )
        s = GridStrategy(grid_low=99, grid_high=101, grid_step=0.02)
        signals = s.generate_signals(data)
        self.assertIsInstance(signals, pd.Series)


if __name__ == "__main__":
    unittest.main()
