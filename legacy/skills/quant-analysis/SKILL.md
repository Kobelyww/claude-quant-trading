---
name: quant-analysis
description: |
  AI-powered market analysis reports using DeepSeek API. Generates professional research reports covering technical analysis, market regime detection, volatility assessment, and risk factor identification from OHLCV data.

  **Perfect for:**
  - Getting a quick market overview before running strategies
  - Understanding market regime (trending vs ranging vs volatile)
  - Technical pattern identification
  - Risk factor analysis and scenario planning

  **Not ideal for:**
  - Fundamental analysis (requires different data sources)
  - Real-time market monitoring
  - Trade execution recommendations
---

# AI Market Analysis

## Overview

This skill uses the DeepSeek API to analyze market data and generate institutional-quality research reports. It processes OHLCV data through technical indicators and statistical tests, then uses AI to interpret the results and write a narrative report.

## Tools

- DeepSeek API via `langchain-deepseek` (`ChatDeepSeek` with model `deepseek-v4-pro`)
- Technical indicators computed directly in Python (numpy/pandas)
- `quant-trading/scripts/performance.py` — for risk metrics

## Critical Constraints

**Data cutoff:**
- Analysis is based on historical data only — no forward-looking statements
- Clearly label all analysis dates and data source

**AI role:**
- AI interprets data patterns, does NOT predict future prices
- All conclusions must be traceable to computed metrics
- Include confidence levels for qualitative assessments

**Report structure:**
Every report must include:
1. Date range and data source
2. Price trend analysis (direction, strength)
3. Volatility assessment
4. Volume analysis
5. Key support/resistance levels
6. Risk factors identified
7. Market regime classification

## Workflow

### Step 1: Prepare Data & Compute Metrics

```python
import pandas as pd
import numpy as np

# Load data
data = pd.read_csv('<SYMBOL>_data.csv', index_col=0, parse_dates=True)
close = data['close']

# Compute metrics
returns = close.pct_change().dropna()
volatility = returns.rolling(20).std() * np.sqrt(252)
ma_20 = close.rolling(20).mean()
ma_60 = close.rolling(60).mean()

# Trend detection
trend = "up" if ma_20.iloc[-1] > ma_60.iloc[-1] else "down"
vol_regime = "high" if volatility.iloc[-1] > volatility.quantile(0.8) else "low"

metrics = {
    "symbol": data['symbol'].iloc[0],
    "start": str(data.index[0]),
    "end": str(data.index[-1]),
    "close_current": close.iloc[-1],
    "return_1m": (close.iloc[-1] / close.iloc[-21] - 1) if len(close) >= 21 else None,
    "return_3m": (close.iloc[-1] / close.iloc[-63] - 1) if len(close) >= 63 else None,
    "volatility_20d": volatility.iloc[-1],
    "trend_direction": trend,
    "vol_regime": vol_regime,
    "avg_volume": data['volume'].tail(20).mean(),
    "high_52w": close.tail(252).max() if len(close) >= 252 else close.max(),
    "low_52w": close.tail(252).min() if len(close) >= 252 else close.min(),
}
```

### Step 2: Generate AI Report

```python
from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv
import os, json

load_dotenv()
llm = ChatDeepSeek(
    model="deepseek-v4-pro",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base=os.getenv("DEEPSEEK_API_BASE"),
)

prompt = f"""
You are a quantitative market analyst. Based on the following metrics, write a concise market analysis report in Chinese.

Metrics:
{json.dumps(metrics, indent=2, default=str)}

Report format:
1. 市场概况 (Market Overview)
2. 趋势分析 (Trend Analysis)
3. 波动率评估 (Volatility Assessment)
4. 成交量分析 (Volume Analysis)
5. 关键价位 (Key Price Levels)
6. 风险因素 (Risk Factors)
7. 市场状态分类 (Market Regime Classification)

Keep each section 2-3 sentences. Be objective and data-driven.
"""

report = llm.invoke(prompt)
print(report.content)
```

### Step 3: Add Risk Assessment

Use `quant-trading/scripts/risk.py` to compute:
- VaR (Value at Risk) at 95% and 99% confidence
- Maximum favorable/adverse excursion
- Kelly criterion position sizing suggestion

### Step 4: Deliver Report

Present a clean markdown report with:
- AI-generated narrative sections
- Computed metrics in tables
- Risk assessment numbers
- Data source and date range disclaimer

## Guardrails

- **No price targets.** Do not predict specific future prices.
- **No buy/sell recommendations.** This is analysis, not advice.
- **Data freshness.** Clearly state the last data point date.
- **Confidence qualifiers.** Use terms like "suggests", "indicates", "shows evidence of" — never "will", "certainly", "guaranteed".
- **Source attribution.** Cite akshare/yfinance/ccxt as data source.
