from django.shortcuts import render, redirect
from django.contrib import messages
from data_center.models import Symbol
from strategies.models import Strategy
from backtest.models import BacktestRun
from analysis.models import AnalysisReport


def settings_page(request):
    from .settings_utils import get_setting, set_setting

    if request.method == "POST":
        api_key = request.POST.get("api_key", "").strip()
        api_base = request.POST.get("api_base", "").strip()
        if not api_base:
            api_base = "https://api.deepseek.com"

        set_setting("DEEPSEEK_API_KEY", api_key)
        set_setting("DEEPSEEK_API_BASE", api_base)
        messages.success(request, "API 配置已保存，即刻生效")
        return redirect("settings")

    key = get_setting("DEEPSEEK_API_KEY")
    base = get_setting("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    return render(request, "dashboard/settings.html", {
        "api_key": key,
        "api_base": base,
        "has_key": bool(key),
    })


def index(request):
    stats = {
        "symbol_count": Symbol.objects.count(),
        "strategy_count": Strategy.objects.count(),
        "backtest_count": BacktestRun.objects.count(),
        "analysis_count": AnalysisReport.objects.count(),
    }
    recent_backtests = BacktestRun.objects.select_related("symbol", "strategy").order_by("-created_at")[:5]
    recent_reports = AnalysisReport.objects.select_related("symbol").order_by("-created_at")[:5]

    return render(request, "dashboard/index.html", {
        "stats": stats,
        "recent_backtests": recent_backtests,
        "recent_reports": recent_reports,
    })
