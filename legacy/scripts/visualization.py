"""可视化模块 - 生成回测结果图表"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def plot_equity_curve(equity: pd.Series, title: str = "Equity Curve",
                      output_path: str = None) -> str:
    """绘制权益曲线"""
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [3, 1]})

    # 权益曲线
    ax1 = axes[0]
    ax1.plot(equity.index, equity.values, color="#2c6fce", linewidth=1.2, label="Equity")
    ax1.axhline(y=equity.iloc[0], color="gray", linestyle="--", alpha=0.5, label="Initial")
    ax1.fill_between(equity.index, equity.iloc[0], equity.values,
                     where=equity.values >= equity.iloc[0], color="#2c6fce", alpha=0.1)
    ax1.fill_between(equity.index, equity.iloc[0], equity.values,
                     where=equity.values < equity.iloc[0], color="#d93a3a", alpha=0.1)
    ax1.set_title(title, fontsize=14, fontweight="bold")
    ax1.set_ylabel("Equity")
    ax1.legend(loc="upper left")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax1.grid(True, alpha=0.3)

    # 回撤曲线
    ax2 = axes[1]
    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak * 100
    ax2.fill_between(equity.index, 0, drawdown.values, color="#d93a3a", alpha=0.3)
    ax2.plot(equity.index, drawdown.values, color="#d93a3a", linewidth=0.8)
    ax2.set_ylabel("Drawdown %")
    ax2.set_xlabel("Date")
    ax2.grid(True, alpha=0.3)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}%"))

    plt.tight_layout()
    path = output_path or "equity_curve.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return path


def plot_monthly_heatmap(equity: pd.Series, output_path: str = None) -> str:
    """月度收益热力图"""
    returns = equity.pct_change().dropna()
    monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)

    pivot = pd.DataFrame({
        "year": monthly.index.year,
        "month": monthly.index.month,
        "return": monthly.values * 100,
    }).pivot(index="year", columns="month", values="return")

    fig, ax = plt.subplots(figsize=(12, max(4, len(pivot) * 0.6)))
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto", vmin=-15, vmax=15)

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    ax.set_xticks(range(12))
    ax.set_xticklabels(months, rotation=45)
    ax.set_yticks(range(len(pivot)))
    ax.set_yticklabels(pivot.index)

    for i in range(len(pivot)):
        for j in range(12):
            val = pivot.iloc[i, j] if j < len(pivot.columns) else np.nan
            if not np.isnan(val):
                ax.text(j, i, f"{val:.1f}%", ha="center", va="center",
                        fontsize=8, color="black" if abs(val) < 8 else "white")

    plt.colorbar(im, ax=ax, label="Return %")
    ax.set_title("Monthly Returns Heatmap", fontsize=14, fontweight="bold")
    plt.tight_layout()

    path = output_path or "monthly_heatmap.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return path


def plot_strategy_comparison(equities: dict, output_path: str = None) -> str:
    """多策略对比图"""
    fig, ax = plt.subplots(figsize=(12, 6))

    colors = ["#2c6fce", "#d93a3a", "#2ea043", "#e28c2d", "#7b4fbf"]
    for i, (name, eq) in enumerate(equities.items()):
        normalized = eq / eq.iloc[0]
        ax.plot(eq.index, normalized.values,
                color=colors[i % len(colors)], linewidth=1.5, label=name)

    ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
    ax.set_title("Strategy Comparison", fontsize=14, fontweight="bold")
    ax.set_ylabel("Normalized Equity")
    ax.set_xlabel("Date")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.2f}x"))

    plt.tight_layout()
    path = output_path or "comparison.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return path


def plot_returns_distribution(equity: pd.Series, output_path: str = None) -> str:
    """收益分布直方图"""
    returns = equity.pct_change().dropna() * 100

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(returns.values, bins=50, color="#2c6fce", alpha=0.7, edgecolor="white")
    ax.axvline(x=returns.mean(), color="red", linestyle="--", linewidth=2,
               label=f"Mean: {returns.mean():.2f}%")
    ax.axvline(x=0, color="gray", linestyle="-", alpha=0.5)
    ax.set_title("Daily Returns Distribution", fontsize=14, fontweight="bold")
    ax.set_xlabel("Return %")
    ax.set_ylabel("Frequency")
    ax.legend()

    plt.tight_layout()
    path = output_path or "returns_dist.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return path
