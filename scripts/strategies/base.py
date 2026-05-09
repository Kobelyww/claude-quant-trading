"""策略抽象基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
import numpy as np


class SignalType(Enum):
    BUY = 1
    SELL = -1
    HOLD = 0


@dataclass
class Signal:
    symbol: str
    date: pd.Timestamp
    signal_type: SignalType
    price: float
    quantity: int = 0
    reason: str = ""


@dataclass
class Portfolio:
    cash: float = 100000.0
    positions: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)

    @property
    def total_value(self) -> float:
        return self.cash


class BaseStrategy(ABC):
    """策略基类"""

    def __init__(self, name: str, params: dict = None):
        self.name = name
        self.params = params or {}

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """根据输入数据生成交易信号

        Args:
            data: 包含 OHLCV 列的 DataFrame

        Returns:
            pd.Series: 信号序列 (1=buy, -1=sell, 0=hold)
        """
        pass

    def on_bar(self, bar: pd.Series, portfolio: Portfolio) -> Signal:
        """每个 bar 的回调（供事件驱动回测使用）"""
        return Signal(
            symbol=bar.get("symbol", ""),
            date=bar.name if isinstance(bar.name, pd.Timestamp) else pd.Timestamp.now(),
            signal_type=SignalType.HOLD,
            price=bar.get("close", 0),
        )

    def __repr__(self):
        return f"{self.name}({self.params})"
