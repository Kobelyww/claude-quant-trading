"""事件驱动回测引擎"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field

from scripts.strategies.base import BaseStrategy, SignalType, Portfolio


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    equity_curve: pd.Series
    trades: List[Dict]
    performance: Dict
    initial_cash: float
    final_equity: float


class BacktestEngine:
    """事件驱动回测引擎"""

    def __init__(self, initial_cash: float = 100000.0,
                 commission: float = 0.0003,
                 slippage: float = 0.001):
        self.initial_cash = initial_cash
        self.commission = commission    # 手续费率
        self.slippage = slippage        # 滑点

    def run(self, data: pd.DataFrame, strategy: BaseStrategy) -> BacktestResult:
        """运行回测

        Args:
            data: OHLCV DataFrame (date index)
            strategy: 策略实例

        Returns:
            BacktestResult: 回测结果
        """
        signals = strategy.generate_signals(data)

        cash = self.initial_cash
        shares = 0
        equity_curve = []
        trades = []
        entry_price = None

        for i in range(len(data)):
            date = data.index[i]
            price = float(data["close"].iloc[i])
            signal = int(signals.iloc[i])

            # 执行交易
            if signal == SignalType.BUY.value and shares == 0:
                # 买入
                exec_price = price * (1 + self.slippage)
                shares = int(cash * 0.95 / exec_price)
                cost = shares * exec_price * (1 + self.commission)
                cash -= cost
                entry_price = exec_price
                trades.append({
                    "date": date, "action": "BUY", "price": exec_price,
                    "shares": shares, "cost": cost, "pnl": 0,
                })

            elif signal == SignalType.SELL.value and shares > 0:
                # 卖出
                exec_price = price * (1 - self.slippage)
                revenue = shares * exec_price * (1 - self.commission)
                pnl = revenue - shares * entry_price if entry_price else 0
                cash += revenue
                trades[-1]["pnl"] = pnl if trades else 0
                trades.append({
                    "date": date, "action": "SELL", "price": exec_price,
                    "shares": shares, "revenue": revenue, "pnl": pnl,
                })
                shares = 0
                entry_price = None

            # 记录权益
            position_value = shares * price
            total_equity = cash + position_value
            equity_curve.append({"date": date, "equity": total_equity})

        # 强制平仓
        if shares > 0:
            final_price = float(data["close"].iloc[-1])
            revenue = shares * final_price * (1 - self.commission)
            pnl = revenue - shares * entry_price if entry_price else 0
            cash += revenue
            if trades and trades[-1]["action"] == "BUY":
                trades[-1]["pnl"] = pnl

        equity = pd.Series(
            [e["equity"] for e in equity_curve],
            index=[e["date"] for e in equity_curve],
        )

        from scripts.performance import performance_report
        perf = performance_report(equity, [t for t in trades if t.get("pnl")])

        return BacktestResult(
            symbol=data["symbol"].iloc[0],
            strategy_name=strategy.name,
            equity_curve=equity,
            trades=trades,
            performance=perf,
            initial_cash=self.initial_cash,
            final_equity=equity.iloc[-1] if len(equity) > 0 else self.initial_cash,
        )

    def run_multiple(self, data: pd.DataFrame,
                     strategies: List[BaseStrategy]) -> Dict[str, BacktestResult]:
        """对同一数据运行多个策略"""
        results = {}
        for s in strategies:
            results[s.name] = self.run(data, s)
        return results

    def compare(self, results: Dict[str, BacktestResult]) -> pd.DataFrame:
        """策略比较"""
        rows = []
        for name, r in results.items():
            rows.append({
                "策略": name,
                "总收益": r.performance.get("总收益率", "N/A"),
                "夏普比率": r.performance.get("夏普比率", "N/A"),
                "最大回撤": r.performance.get("最大回撤", "N/A"),
                "胜率": r.performance.get("胜率", "N/A"),
                "交易次数": r.performance.get("交易次数", "N/A"),
            })
        return pd.DataFrame(rows)
