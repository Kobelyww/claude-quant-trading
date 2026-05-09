---
name: quant-strategy
description: |
  AI-powered trading strategy generation and analysis using DeepSeek API. Generates Python strategy code from natural language descriptions, analyzes strategy logic, identifies potential flaws, and suggests parameter optimizations. Works with all four built-in strategy templates.

  **Perfect for:**
  - Converting a trading idea into executable Python strategy code
  - Getting an AI review of strategy logic and potential edge cases
  - Generating strategy variants with different parameters
  - Explaining why a strategy works (or doesn't) in specific market conditions

  **Not ideal for:**
  - Production execution (AI-generated code needs human review)
  - Real-time signal generation (use backtest engine for that)
  - Predicting future market movements
---

# AI Strategy Generation

## Overview

This skill uses the DeepSeek API to generate, analyze, and refine quantitative trading strategies. It can create new strategy code from natural language descriptions, review existing strategies for flaws, and suggest improvements based on market theory.

## Tools

- DeepSeek API via `langchain-deepseek` (`ChatDeepSeek` with model `deepseek-v4-pro`)
- `quant-trading/scripts/strategies/` — built-in strategy templates
- `quant-trading/scripts/backtest_engine.py` — for validation

## Critical Constraints

**AI Role:**
- The AI is an analyst, NOT an advisor. All generated strategies are for research only.
- Always include a risk disclaimer with AI-generated strategy code.
- Never claim a strategy will be profitable.

**Code Quality:**
- Generated strategies MUST subclass `BaseStrategy` and implement `generate_signals()`.
- Use only numpy/pandas — no external ML libraries in generated strategies.
- Always include parameter documentation in generated code.

**Validation:**
- Every AI-generated strategy must pass a backtest before being presented.
- If backtest fails, fix the strategy code and re-run before delivering.

## Workflow

### Step 1: Understand the Trading Idea

Clarify with the user:
- What market condition does it exploit? (trend, mean reversion, breakout, etc.)
- What is the entry condition?
- What is the exit condition?
- Any position sizing or risk management rules?

### Step 2: Generate Strategy Code

Use DeepSeek API to generate the strategy:

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
Generate a Python trading strategy class that subclasses BaseStrategy.
The strategy should: {user_description}

BaseStrategy interface:
class BaseStrategy(ABC):
    def __init__(self, name: str, params: dict = None)
    def generate_signals(self, data: pd.DataFrame) -> pd.Series  # 1=buy, -1=sell, 0=hold

Output ONLY the Python code, no explanation.
"""

response = llm.invoke(prompt)
# Save response.content to scripts/strategies/<name>.py
```

### Step 3: Validate with Backtest

Run the generated strategy through the backtest engine with sample data. If errors occur, feed them back to the AI for correction.

### Step 4: AI Strategy Review

After backtest, ask DeepSeek to analyze:
1. Signal frequency and clustering
2. Win/loss pattern consistency
3. Market regime dependency
4. Parameter sensitivity analysis
5. Potential improvements

### Step 5: Deliver

Present:
1. The strategy code (with docstring)
2. Backtest performance summary
3. AI review and suggestions
4. Risk disclaimer

## Guardrails

- **⚠️ AI-GENERATED CODE WARNING.** Must display a clear disclaimer that AI-generated strategies are for research only and have not been validated for live trading.
- **Always backtest before presenting.** Never show a strategy without performance metrics.
- **Fix errors silently.** If backtest fails, use AI to fix the code and re-run. Only surface to user if fixes fail 3 times.
- **No black-box ML.** Strategies should be rule-based and explainable. Do not generate neural network trading models.
