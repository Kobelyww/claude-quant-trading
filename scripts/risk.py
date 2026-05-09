"""风险管理模块"""

import pandas as pd
import numpy as np


def kelly_criterion(win_rate: float, profit_loss_ratio: float) -> float:
    """凯利公式计算最优仓位比例

    Args:
        win_rate: 胜率 (0-1)
        profit_loss_ratio: 盈亏比 (avg_win / avg_loss)
    Returns:
        建议仓位比例 (如 0.2 表示 20%)
    """
    if profit_loss_ratio <= 0:
        return 0.0
    f = win_rate - (1 - win_rate) / profit_loss_ratio
    return max(0.0, min(f, 0.5))


def atr_stop_loss(data: pd.DataFrame, period: int = 14,
                  multiplier: float = 2.0) -> pd.Series:
    """ATR 动态止损位

    Args:
        data: OHLCV DataFrame
        period: ATR 周期
        multiplier: ATR 倍数
    Returns:
        pd.Series: 止损价格序列
    """
    high, low, close = data["high"], data["low"], data["close"]

    tr = pd.DataFrame({
        "hl": high - low,
        "hc": (high - close.shift()).abs(),
        "lc": (low - close.shift()).abs(),
    }).max(axis=1)

    atr = tr.rolling(period).mean()
    stop_price = close - multiplier * atr
    return stop_price


def position_size(equity: float, price: float, risk_pct: float = 0.02,
                  stop_distance: float = None) -> int:
    """基于风险的仓位计算

    Args:
        equity: 当前权益
        price: 入场价格
        risk_pct: 每笔交易风险比例 (默认2%)
        stop_distance: 止损距离（价格差），None 则按固定比例
    Returns:
        建议股数
    """
    risk_amount = equity * risk_pct
    if stop_distance and stop_distance > 0:
        size = risk_amount / stop_distance
    else:
        size = equity * 0.2 / price
    return max(int(size // 100 * 100), 0)


def risk_check(portfolio_value: float, peak_value: float,
               max_dd_limit: float = 0.20) -> tuple:
    """风险检查

    Returns:
        (is_safe, current_drawdown, message)
    """
    current_dd = (peak_value - portfolio_value) / peak_value
    if current_dd > max_dd_limit:
        return False, current_dd, f"回撤超限: {current_dd*100:.1f}% > {max_dd_limit*100:.0f}%"
    return True, current_dd, "OK"
