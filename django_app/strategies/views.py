import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Strategy


def strategy_list(request):
    strategies = Strategy.objects.all()
    return render(request, "strategies/list.html", {"strategies": strategies})


def strategy_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        strategy_type = request.POST.get("strategy_type", "ma_cross")
        code = request.POST.get("code", "").strip()
        is_ai = request.POST.get("is_ai_generated") == "on"

        if not name:
            messages.error(request, "请输入策略名称")
            return redirect("strategy_list")

        params = {}
        if strategy_type == "ma_cross":
            params = {"short_window": int(request.POST.get("short_window", 5)),
                       "long_window": int(request.POST.get("long_window", 20))}
        elif strategy_type == "momentum":
            params = {"lookback": int(request.POST.get("lookback", 20))}
        elif strategy_type == "mean_reversion":
            params = {"window": int(request.POST.get("window", 20)),
                       "num_std": float(request.POST.get("num_std", 2.0))}
        elif strategy_type == "grid":
            params = {"grid_step": float(request.POST.get("grid_step", 0.02))}

        Strategy.objects.create(name=name, strategy_type=strategy_type,
                                params=params, code=code, is_ai_generated=is_ai)
        messages.success(request, f"策略 '{name}' 创建成功")
        return redirect("strategy_list")

    return render(request, "strategies/create.html", {"type_choices": Strategy.TYPE_CHOICES})


def strategy_ai_generate(request):
    if request.method == "POST":
        description = request.POST.get("description", "").strip()
        if not description:
            messages.error(request, "请描述你的交易思路")
            return redirect("strategy_list")

        try:
            from langchain_deepseek import ChatDeepSeek
            from django.conf import settings

            llm = ChatDeepSeek(model="deepseek-v4-pro",
                               api_key=settings.DEEPSEEK_API_KEY,
                               api_base=settings.DEEPSEEK_API_BASE)
            prompt = f"""Generate a Python trading strategy class that subclasses BaseStrategy.
Trading idea: {description}

Use this exact template:
```python
from scripts.strategies.base import BaseStrategy, SignalType
import pandas as pd; import numpy as np
class CustomStrategy(BaseStrategy):
    def __init__(self, params: dict = None):
        super().__init__("custom_strategy", params or {{}})
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = pd.Series(SignalType.HOLD.value, index=data.index, dtype=int)
        # YOUR LOGIC HERE
        return signals
```
Output ONLY the Python code."""
            response = llm.invoke(prompt)
            code = response.content.strip()
            if code.startswith("```python"):
                code = code[9:]
            if code.endswith("```"):
                code = code[:-3]

            Strategy.objects.create(name=f"AI: {description[:40]}", strategy_type="custom",
                                    code=code.strip(), is_ai_generated=True)
            messages.success(request, "AI 策略生成成功")
        except Exception as e:
            messages.error(request, f"AI 生成失败: {str(e)}")
        return redirect("strategy_list")

    return render(request, "strategies/ai_generate.html")


def strategy_detail(request, strategy_id):
    strategy = get_object_or_404(Strategy, pk=strategy_id)
    return render(request, "strategies/detail.html", {"strategy": strategy})


def strategy_edit(request, strategy_id):
    strategy = get_object_or_404(Strategy, pk=strategy_id)
    if request.method == "POST":
        strategy.name = request.POST.get("name", "").strip()
        strategy.code = request.POST.get("code", "").strip()
        params_str = request.POST.get("params_json", "").strip()
        if params_str:
            try:
                strategy.params = json.loads(params_str)
            except json.JSONDecodeError:
                pass
        strategy.save()
        messages.success(request, "策略已更新")
        return redirect("strategy_detail", strategy_id=strategy.id)
    return render(request, "strategies/edit.html", {"strategy": strategy})


def strategy_delete(request, strategy_id):
    strategy = get_object_or_404(Strategy, pk=strategy_id)
    strategy.delete()
    messages.success(request, "策略已删除")
    return redirect("strategy_list")
