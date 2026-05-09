"""双均线交叉策略 - 金叉买入，死叉卖出"""

import pandas as pd
import numpy as np
from scripts.strategies.base import BaseStrategy
from scripts.strategies.base import SignalType


class MACrossStrategy(BaseStrategy):
    """双均线策略：短期均线上穿长期均线买入，下穿卖出"""

    def __init__(self, short_window: int = 5, long_window: int = 20, params: dict = None):
        merged = {"short_window": short_window, "long_window": long_window}
        if params:
            merged.update(params)
        super().__init__(f"ma_cross({short_window},{long_window})", merged)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        short_w = self.params["short_window"]
        long_w = self.params["long_window"]
        signals = pd.Series(SignalType.HOLD.value, index=data.index, dtype=int)

        close = data["close"]
        ma_short = close.rolling(short_w).mean()
        ma_long = close.rolling(long_w).mean()

        cross_above = (ma_short > ma_long) & (ma_short.shift(1) <= ma_long.shift(1))
        cross_below = (ma_short < ma_long) & (ma_short.shift(1) >= ma_long.shift(1))

        signals[cross_above] = SignalType.BUY.value
        signals[cross_below] = SignalType.SELL.value

        return signals
