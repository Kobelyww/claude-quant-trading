"""动量策略 - 基于价格动量排名选股"""

import pandas as pd
import numpy as np
from scripts.strategies.base import BaseStrategy
from scripts.strategies.base import SignalType


class MomentumStrategy(BaseStrategy):
    """动量策略：过去N日涨幅排名前K的标的做多"""

    def __init__(self, lookback: int = 20, top_k: int = 5, params: dict = None):
        merged = {"lookback": lookback, "top_k": top_k}
        if params:
            merged.update(params)
        super().__init__(f"momentum({lookback})", merged)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        Args:
            data: 单标的 OHLCV DataFrame, 必须有 'close' 列
        Returns:
            pd.Series: 信号序列
        """
        lookback = self.params["lookback"]
        signals = pd.Series(SignalType.HOLD.value, index=data.index, dtype=int)

        momentum = data["close"].pct_change(lookback)
        ma_short = data["close"].rolling(10).mean()

        for i in range(lookback + 1, len(data)):
            if momentum.iloc[i] > 0 and data["close"].iloc[i] > ma_short.iloc[i]:
                signals.iloc[i] = SignalType.BUY.value
            elif momentum.iloc[i] < -0.05:
                signals.iloc[i] = SignalType.SELL.value

        return signals
