"""绩效指标计算模块"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple


def calc_sharpe_ratio(returns: pd.Series, risk_free: float = 0.03,
                      periods_per_year: int = 252) -> float:
    """夏普比率"""
    excess = returns - risk_free / periods_per_year
    std = excess.std()
    if std < 1e-10:
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def calc_max_drawdown(equity: pd.Series) -> Tuple[float, pd.Timestamp, pd.Timestamp]:
    """最大回撤及起止时间"""
    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak
    max_dd = drawdown.min()
    if max_dd == 0 or pd.isna(max_dd):
        return 0.0, equity.index[0], equity.index[-1]
    dd_end = drawdown.idxmin()
    dd_start = equity[:dd_end].idxmax() if len(equity[:dd_end]) > 0 else equity.index[0]
    return max_dd, dd_start, dd_end


def calc_calmar_ratio(returns: pd.Series, equity: pd.Series,
                      periods_per_year: int = 252) -> float:
    """卡尔玛比率（年化收益/最大回撤）"""
    ann_return = returns.mean() * periods_per_year
    max_dd, _, _ = calc_max_drawdown(equity)
    if max_dd == 0:
        return 0.0
    return ann_return / abs(max_dd)


def calc_win_rate(trades: list) -> float:
    """胜率"""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t["pnl"] > 0)
    return wins / len(trades)


def calc_profit_loss_ratio(trades: list) -> float:
    """盈亏比"""
    if not trades:
        return 0.0
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 1
    return avg_win / avg_loss if avg_loss else 0.0


def calc_annual_return(equity: pd.Series, periods_per_year: int = 252) -> float:
    """年化收益率"""
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    years = len(equity) / periods_per_year
    if years == 0:
        return 0.0
    return (1 + total_return) ** (1 / years) - 1


def calc_annual_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    """年化波动率"""
    return returns.std() * np.sqrt(periods_per_year)


def performance_report(equity: pd.Series, trades: list,
                       risk_free: float = 0.03,
                       periods_per_year: int = 252) -> Dict:
    """生成完整绩效报告"""
    returns = equity.pct_change().dropna()

    max_dd, dd_start, dd_end = calc_max_drawdown(equity)

    return {
        "初始资金": equity.iloc[0],
        "最终权益": equity.iloc[-1],
        "总收益率": f"{(equity.iloc[-1] / equity.iloc[0] - 1) * 100:.2f}%",
        "年化收益率": f"{calc_annual_return(equity, periods_per_year) * 100:.2f}%",
        "年化波动率": f"{calc_annual_volatility(returns, periods_per_year) * 100:.2f}%",
        "夏普比率": f"{calc_sharpe_ratio(returns, risk_free, periods_per_year):.3f}",
        "卡尔玛比率": f"{calc_calmar_ratio(returns, equity, periods_per_year):.3f}",
        "最大回撤": f"{max_dd * 100:.2f}%",
        "最大回撤起始": str(dd_start),
        "最大回撤结束": str(dd_end),
        "交易次数": len(trades),
        "胜率": f"{calc_win_rate(trades) * 100:.1f}%",
        "盈亏比": f"{calc_profit_loss_ratio(trades):.2f}",
    }
