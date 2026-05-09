# Claude Quant Trading

Claude Code 量化交易技能插件 — 多市场数据获取、事件驱动回测、AI 策略生成、市场分析报告，全部通过自然语言驱动。

> [!IMPORTANT]
> 本插件仅供研究和学习用途。所有回测结果、AI 生成的策略和分析报告均不构成投资建议。策略代码需经人工审查后方可用于实盘交易。历史回测表现不代表未来收益。

## 功能概览

| 功能 | 说明 |
|------|------|
| **多市场数据** | A 股（akshare）、美股（yfinance）、加密货币（ccxt/binance），统一 OHLCV 格式 |
| **策略回测** | 事件驱动引擎，含手续费（万三）、滑点模拟，输出专业绩效指标 |
| **AI 策略生成** | DeepSeek API 驱动，自然语言描述交易思路 → 可执行 Python 策略代码 |
| **AI 市场分析** | 技术面分析、市场状态识别、波动率评估、风险因素报告 |
| **策略筛选** | 多条件量化选股/选币 |

## 快速安装

```bash
# 添加插件市场
claude plugin marketplace add Kobelyww/claude-quant-trading

# 安装插件
claude plugin install quant-trading@claude-quant-trading
```

### 环境要求

安装 Python 依赖：

```bash
pip install akshare yfinance ccxt pandas numpy matplotlib langchain-deepseek python-dotenv
```

配置 DeepSeek API（用于 AI 分析和策略生成）：

```bash
# .env 文件
DEEPSEEK_API_KEY="your-api-key"
DEEPSEEK_API_BASE="https://api.deepseek.com"
```

## 斜杠命令

| 命令 | 用法 | 说明 |
|------|------|------|
| `/fetch` | `/fetch 000001 --start 20240101` | 拉取历史行情数据 |
| `/backtest` | `/backtest ma_cross --symbol 000001` | 运行策略回测 |
| `/analyze` | `/analyze AAPL --mode full` | AI 市场分析报告 |
| `/screen` | `/screen --market a_stock --top 20` | 多条件量化筛选 |

## 内置策略

| 策略 | 参数 | 适用场景 |
|------|------|----------|
| `ma_cross` | `short_window=5, long_window=20` | 趋势跟踪，金叉/死叉 |
| `momentum` | `lookback=20` | 动量延续 |
| `mean_reversion` | `window=20, num_std=2.0` | 区间震荡，布林带回归 |
| `grid` | `grid_low, grid_high, grid_step=0.02` | 横盘/高波动 |

### 自定义策略参数

```
/backtest ma_cross --symbol 000001 --params short_window=10,long_window=30 --cash 200000
```

## 技能架构

```
quant-trading/
├── .claude-plugin/plugin.json     # 插件元数据
├── skills/                        # 4 个技能
│   ├── quant-data/                # 数据获取
│   ├── quant-backtest/            # 策略回测
│   ├── quant-strategy/            # AI 策略生成
│   └── quant-analysis/            # AI 市场分析
├── commands/                      # 4 个斜杠命令
│   ├── fetch.md                   # /fetch
│   ├── backtest.md                # /backtest
│   ├── analyze.md                 # /analyze
│   └── screen.md                  # /screen
├── scripts/                       # Python 核心引擎
│   ├── backtest_engine.py         # 事件驱动回测循环
│   ├── data_fetcher.py            # 多市场数据统一接口
│   ├── performance.py             # 绩效指标计算
│   ├── risk.py                    # 风险管理模块
│   ├── visualization.py           # 图表生成（matplotlib）
│   └── strategies/                # 策略库
│       ├── base.py                # 策略基类
│       ├── ma_cross.py            # 双均线策略
│       ├── momentum.py            # 动量策略
│       ├── mean_reversion.py      # 均值回归策略
│       └── grid.py                # 网格交易策略
└── tests/                         # 37 个单元测试
```

## 使用示例

### 1. 拉取数据

```
/fetch 000001 --start 20240101 --end 20241231
/fetch AAPL --market us_stock
/fetch BTC/USDT
```

### 2. 回测策略

```
/backtest ma_cross --symbol 000001 --params short_window=10,long_window=30
/backtest mean_reversion --symbol AAPL --params window=20,num_std=2.0
```

回测输出示例：

```
初始资金: 100000.0
最终权益: 112350.42
总收益率: 12.35%
年化收益率: 11.72%
年化波动率: 18.30%
夏普比率: 0.487
卡尔玛比率: 0.682
最大回撤: -15.32%
交易次数: 23
胜率: 52.2%
盈亏比: 1.85
```

同时自动生成三张图表：权益曲线+回撤、月度收益热力图、收益分布直方图。

### 3. AI 市场分析

```
/analyze AAPL
/analyze 000001 --mode risk
```

生成含以下章节的中文分析报告：市场概况、趋势分析、波动率评估、成交量分析、关键价位、风险因素、市场状态分类。

### 4. 量化筛选

```
/screen --market a_stock --top 10
/screen --market crypto --conditions "volume_ratio_5d>2"
```

## 回测引擎特性

- **事件驱动** — 按时间序列逐 bar 处理，避免前视偏差
- **手续费模拟** — 默认 0.03%（万三），可配置
- **滑点模拟** — 默认 0.1%
- **绩效指标** — 夏普比率、最大回撤、卡尔玛比率、胜率、盈亏比、年化收益/波动
- **风险模块** — Kelly 公式仓位建议、ATR 动态止损、风险限制检查
- **图表输出** — 权益曲线、回撤图、月度热力图、收益分布、多策略对比

## 编写自定义策略

所有策略需继承 `BaseStrategy` 并实现 `generate_signals()`：

```python
from scripts.strategies.base import BaseStrategy, SignalType
import pandas as pd
import numpy as np

class MyStrategy(BaseStrategy):
    def __init__(self, threshold: float = 0.05, params: dict = None):
        merged = {"threshold": threshold}
        if params:
            merged.update(params)
        super().__init__("my_strategy", merged)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(SignalType.HOLD.value, index=data.index, dtype=int)
        returns = data["close"].pct_change()

        for i in range(1, len(data)):
            if returns.iloc[i] > self.params["threshold"]:
                signals.iloc[i] = SignalType.BUY.value
            elif returns.iloc[i] < -self.params["threshold"]:
                signals.iloc[i] = SignalType.SELL.value

        return signals
```

也可以直接用自然语言描述策略思路，让 AI 生成代码：

```
请根据我的交易思路生成策略代码：当价格突破20日高点且成交量放大1.5倍时买入，
当价格跌破10日低点或盈利超过15%时卖出。
```

## 运行测试

```bash
cd quant-trading
python -m unittest discover -s tests -v
```

## Django Web 应用 (`django-app` 分支)

本仓库还包含一个完整的 Django Web 界面，可在浏览器中操作所有量化功能。

```bash
# 切换到 Django 分支
git checkout django-app

# 安装依赖
pip install django langchain-deepseek python-dotenv

# 配置 DeepSeek API（用于 AI 功能）
cp ../.env .env  # 或手动创建

# 初始化数据库
cd django_app
python manage.py migrate

# 启动服务
python manage.py runserver
# 访问 http://localhost:8000
```

### Web 功能

| 模块 | 路径 | 功能 |
|------|------|------|
| 仪表盘 | `/` | 统计概览、快捷入口 |
| 数据管理 | `/data/` | 添加标的、拉取行情、预览K线 |
| 策略管理 | `/strategies/` | 手动创建 / AI 生成策略代码 |
| 回测中心 | `/backtest/` | 运行回测、ECharts 交互图表、多策略对比 |
| AI 分析 | `/analysis/` | DeepSeek 生成市场分析报告 |

### 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Django 5.x + SQLite |
| 前端 | Bootstrap 5 + ECharts 5 + Marked.js |
| 量化引擎 | 复用 `scripts/` 全部模块 |
| AI | DeepSeek API (langchain-deepseek) |

## 许可

MIT License

---

**免责声明：本插件仅供研究学习使用。AI 生成的策略和分析不构成投资建议。量化交易存在风险，历史回测不代表未来表现。**
