import json
import pandas as pd
import numpy as np
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import AnalysisReport
from data_center.models import Symbol
from dashboard.settings_utils import get_setting


def analysis_list(request):
    reports = AnalysisReport.objects.select_related("symbol").all()
    return render(request, "analysis/list.html", {"reports": reports})


def analysis_run(request):
    if request.method == "POST":
        symbol_id = request.POST.get("symbol_id")
        report_type = request.POST.get("report_type", "full")
        symbol = get_object_or_404(Symbol, pk=symbol_id)

        data_qs = symbol.marketdata_set.all().order_by("date")
        if data_qs.count() < 20:
            messages.error(request, "数据不足（至少需要20条）")
            return redirect("analysis_list")

        try:
            close = [d.close for d in data_qs]
            returns = pd.Series(close).pct_change().dropna()
            vol_20 = float(returns.tail(20).std() * np.sqrt(252))
            ma20 = sum(close[-20:]) / 20
            ma60 = sum(close[-60:]) / 60 if len(close) >= 60 else ma20

            metrics = {
                "symbol": symbol.code,
                "bars": len(close),
                "close": round(close[-1], 2),
                "return_1m": f"{(close[-1]/close[-21]-1)*100:.1f}%" if len(close) >= 21 else "N/A",
                "volatility": f"{vol_20*100:.1f}%",
                "trend": "上涨" if ma20 > ma60 else "下跌",
                "high_1y": round(max(close[-252:]), 2) if len(close) >= 252 else round(max(close), 2),
                "low_1y": round(min(close[-252:]), 2) if len(close) >= 252 else round(min(close), 2),
                "avg_volume": int(sum(d.volume for d in data_qs) / len(data_qs)),
            }

            from langchain_deepseek import ChatDeepSeek
            llm = ChatDeepSeek(model="deepseek-v4-pro",
                               api_key=get_setting("DEEPSEEK_API_KEY"),
                               api_base=get_setting("DEEPSEEK_API_BASE", "https://api.deepseek.com"))
            prompt = f"""You are a quantitative analyst. Write a market analysis report in Chinese based on these metrics:
{json.dumps(metrics, ensure_ascii=False)}

Format:
## 市场概况 | ## 趋势分析 | ## 波动率评估 | ## 成交量分析 | ## 关键价位 | ## 风险因素 | ## 市场状态

Be concise, data-driven. No price predictions."""

            response = llm.invoke(prompt)
            content = response.content.strip()

            AnalysisReport.objects.create(
                symbol=symbol, report_type=report_type,
                content=content, metrics_json=metrics,
            )
            messages.success(request, f"{symbol.code} 分析报告生成成功")
        except Exception as e:
            messages.error(request, f"分析失败: {str(e)}")
        return redirect("analysis_list")

    symbols = Symbol.objects.all()
    return render(request, "analysis/run.html", {"symbols": symbols, "types": AnalysisReport.TYPE_CHOICES})


def analysis_detail(request, report_id):
    report = get_object_or_404(AnalysisReport, pk=report_id)
    return render(request, "analysis/detail.html", {"report": report})
