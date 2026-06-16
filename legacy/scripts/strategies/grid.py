"""网格交易策略 - 在价格区间内分批买入卖出"""

import pandas as pd
import numpy as np
from scripts.strategies.base import BaseStrategy
from scripts.strategies.base import SignalType


class GridStrategy(BaseStrategy):
    """网格策略：在设定价格区间内，每跌grid_step买入，每涨grid_step卖出"""

    def __init__(self, grid_low: float = None, grid_high: float = None,
                 grid_step: float = 0.02, params: dict = None):
        merged = {"grid_low": grid_low, "grid_high": grid_high, "grid_step": grid_step}
        if params:
            merged.update(params)
        super().__init__(f"grid({grid_step})", merged)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        grid_step = self.params["grid_step"]
        signals = pd.Series(SignalType.HOLD.value, index=data.index, dtype=int)

        close = data["close"]

        grid_low = self.params["grid_low"] or close.min()
        grid_high = self.params["grid_high"] or close.max()
        grid_count = int((grid_high - grid_low) / (grid_low * grid_step))

        if grid_count < 2:
            return signals

        grid_levels = np.linspace(grid_low, grid_high, grid_count)
        last_grid = None

        for i in range(len(data)):
            price = close.iloc[i]
            grid_idx = np.searchsorted(grid_levels, price)

            if last_grid is None:
                last_grid = grid_idx
                continue

            if grid_idx < last_grid:
                signals.iloc[i] = SignalType.BUY.value
            elif grid_idx > last_grid:
                signals.iloc[i] = SignalType.SELL.value

            last_grid = grid_idx

        return signals
