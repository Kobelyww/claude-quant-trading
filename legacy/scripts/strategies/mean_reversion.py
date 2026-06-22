"""均值回归策略 - 价格偏离均值后反向交易"""

import pandas as pd
import numpy as np
from scripts.strategies.base import BaseStrategy
from scripts.strategies.base import SignalType


class MeanReversionStrategy(BaseStrategy):
    """布林带均值回归：触及下轨买入，触及上轨卖出"""

    def __init__(self, window: int = 20, num_std: float = 2.0, params: dict = None):
        merged = {"window": window, "num_std": num_std}
        if params:
            merged.update(params)
        super().__init__(f"mean_reversion({window},{num_std})", merged)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        window = self.params["window"]
        num_std = self.params["num_std"]
        signals = pd.Series(SignalType.HOLD.value, index=data.index, dtype=int)

        close = data["close"]
        ma = close.rolling(window).mean()
        std = close.rolling(window).std()
        upper_band = ma + num_std * std
        lower_band = ma - num_std * std

        for i in range(window, len(data)):
            if close.iloc[i] <= lower_band.iloc[i]:
                signals.iloc[i] = SignalType.BUY.value
            elif close.iloc[i] >= upper_band.iloc[i]:
                signals.iloc[i] = SignalType.SELL.value

        return signals
