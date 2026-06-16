---
description: Generate AI-powered market analysis report using DeepSeek
argument-hint: "<symbol> [--mode technical|regime|risk|full]"
---

# AI Market Analysis

Generate a professional quantitative market analysis report using DeepSeek API. Covers technical analysis, market regime detection, volatility assessment, and risk factor identification.

## Workflow

### Step 1: Load Data

Use existing `<SYMBOL>_data.csv` or fetch with `/fetch` first.

### Step 2: Compute Technical Metrics

Load the `quant-analysis` skill and compute:

```bash
cd quant-trading && python3 -c "
import pandas as pd
import numpy as np
import json

data = pd.read_csv('<SYMBOL>_data.csv', index_col=0, parse_dates=True)
close = data['close']
returns = close.pct_change().dropna()
vol_20 = returns.rolling(20).std() * np.sqrt(252)
ma_20 = close.rolling(20).mean()
ma_60 = close.rolling(60).mean()
trend = 'up' if ma_20.iloc[-1] > ma_60.iloc[-1] else 'down'

metrics = {
    'symbol': '<SYMBOL>',
    'data_start': str(data.index[0]),
    'data_end': str(data.index[-1]),
    'bars': len(data),
    'close': round(close.iloc[-1], 2),
    'return_1m': f\"{(close.iloc[-1]/close.iloc[-21]-1)*100:.2f}%\" if len(close)>=21 else 'N/A',
    'return_3m': f\"{(close.iloc[-1]/close.iloc[-63]-1)*100:.2f}%\" if len(close)>=63 else 'N/A',
    'volatility_annualized': f\"{vol_20.iloc[-1]*100:.1f}%\",
    'trend': trend,
    'vol_percentile': f\"{(vol_20.iloc[-1] < vol_20).mean()*100:.0f}%\",
    'high_52w': round(close.tail(252).max(), 2) if len(close)>=252 else round(close.max(), 2),
    'low_52w': round(close.tail(252).min(), 2) if len(close)>=252 else round(close.min(), 2),
    'avg_volume_20d': int(data['volume'].tail(20).mean()),
}
print(json.dumps(metrics, indent=2, ensure_ascii=False))
"
```

### Step 3: Generate AI Report

```python
from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv
import os

load_dotenv()
llm = ChatDeepSeek(
    model="deepseek-v4-pro",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base=os.getenv("DEEPSEEK_API_BASE"),
)

prompt = f"""
You are a quantitative market analyst. Based on these metrics, write a concise market analysis report in Chinese:

{metrics_json}

Report structure:
1. 市场概况 - One-sentence summary of current state
2. 趋势分析 - Trend direction, strength, MA relationship
3. 波动率评估 - Current vol vs historical, regime classification
4. 成交量分析 - Volume trend and anomalies
5. 关键价位 - Support/resistance from 52w high/low and MA levels
6. 风险因素 - Key risks based on the data
7. 市场状态 - Classification (strong trend / weak trend / range-bound / high vol)

Keep it concise, data-driven, objective. No price predictions or trading advice.
"""

report = llm.invoke(prompt)
print(report.content)
```

### Step 4: Deliver

Present the AI-generated report in clean markdown format with:
- Section headers matching the structure above
- Metrics table at the top
- Date range and data source disclaimer at the bottom

## Modes

- `technical`: Focus on price action, MAs, support/resistance
- `regime`: Focus on market regime classification
- `risk`: Focus on VaR, drawdown analysis, risk factors
- `full`: All of the above (default)

## Example

```
/analyze AAPL
/analyze 000001 --mode risk
/analyze BTC/USDT --mode regime
```
