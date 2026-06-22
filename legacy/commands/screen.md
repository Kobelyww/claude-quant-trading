---
description: Screen stocks by quantitative criteria across markets
argument-hint: "[--market auto|a_stock|us_stock|crypto] [--conditions <filters>] [--sort <metric>] [--top 20]"
---

# Quantitative Stock Screening

Screen stocks and crypto assets using quantitative filters. Supports cross-market screening with customizable conditions.

## Workflow

### Step 1: Define Screening Conditions

Common filters:

| Filter | Description | Example |
|--------|-------------|---------|
| `price_change` | Price change % over N days | `price_change_20d>5` |
| `volume_ratio` | Volume vs N-day average | `volume_ratio_5d>1.5` |
| `volatility` | Annualized volatility | `volatility_20d<0.4` |
| `ma_position` | Price vs MA | `ma_position_20>0` (above MA20) |
| `rsi` | RSI value | `rsi_14<30` (oversold) |
| `turnover` | Turnover rate | `turnover>5` |

### Step 2: Run Screener

```bash
cd quant-trading && python3 -c "
import pandas as pd
import numpy as np

# Load watchlist or use a default list
symbols = ['000001', '600519', '000858', '600036', '000333']

results = []
for sym in symbols:
    try:
        df = pd.read_csv(f'{sym}_data.csv', index_col=0, parse_dates=True)
        if len(df) < 20:
            continue
        close = df['close']
        returns = close.pct_change().dropna()

        results.append({
            'symbol': sym,
            'close': round(close.iloc[-1], 2),
            'ret_5d': f\"{(close.iloc[-1]/close.iloc[-5]-1)*100:.1f}%\",
            'ret_20d': f\"{(close.iloc[-1]/close.iloc[-20]-1)*100:.1f}%\",
            'vol_20d': f\"{returns.tail(20).std()*np.sqrt(252)*100:.1f}%\",
            'above_ma20': 'Yes' if close.iloc[-1] > close.rolling(20).mean().iloc[-1] else 'No',
            'above_ma60': 'Yes' if close.iloc[-1] > close.rolling(60).mean().iloc[-1] else 'No',
            'vol_ratio': f\"{df['volume'].iloc[-1]/df['volume'].tail(20).mean():.2f}x\",
        })
    except:
        pass

screened = pd.DataFrame(results)
screened = screened.sort_values('<SORT_COL>', ascending=False)
print(screened.to_markdown(index=False))
"
```

### Step 3: Apply Custom Filters

Parse user conditions from `--conditions` flag and filter the results table accordingly.

### Step 4: Present Results

Display as a sortable table with:
- Symbol, price, key metrics
- Highlight cells meeting filter criteria
- Option to save results for further analysis

## Example

```
/screen --market a_stock --conditions "volatility_20d<0.4,price_change_20d>0" --sort price_change_20d --top 10
/screen --market us_stock --top 20
/screen --market crypto --conditions "volume_ratio_5d>2"
```
