from django.shortcuts import render
from data_center.models import Symbol
from strategies.models import Strategy
from backtest.models import BacktestRun
from analysis.models import AnalysisReport


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
