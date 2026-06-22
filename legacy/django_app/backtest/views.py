import json
import threading
import pandas as pd
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from .models import BacktestRun
from data_center.models import Symbol, MarketData
from strategies.models import Strategy
from scripts.backtest_engine import BacktestEngine
from scripts.strategies import (
    MACrossStrategy, MomentumStrategy, MeanReversionStrategy, GridStrategy,
)

STRATEGY_CLASS_MAP = {
    "ma_cross": MACrossStrategy,
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "grid": GridStrategy,
}


def _run_backtest_thread(run_id):
    """后台线程执行回测"""
    run = BacktestRun.objects.get(pk=run_id)
    run.status = "running"
    run.save()

    try:
        data_qs = run.symbol.marketdata_set.filter(
            date__gte=run.start_date, date__lte=run.end_date
        ).order_by("date")

        if data_qs.count() < 20:
            raise ValueError("数据不足（至少需要20条）")

        df = pd.DataFrame(list(data_qs.values(
            "date", "open", "high", "low", "close", "volume", "symbol_id"
        )))
        df["symbol"] = run.symbol.code
        df = df.set_index("date")

        stype = run.strategy.strategy_type
        params = run.strategy.params or {}

        if stype == "custom" and run.strategy.code:
            import tempfile, os
            code = run.strategy.code
            ns = {}
            exec(code, {"pd": pd, "np": __import__("numpy")}, ns)
            for v in ns.values():
                if isinstance(v, type) and hasattr(v, "generate_signals"):
                    strategy = v(**params)
                    break
            else:
                raise ValueError("自定义策略代码中未找到有效策略类")
        elif stype in STRATEGY_CLASS_MAP:
            strategy = STRATEGY_CLASS_MAP[stype](**params)
        else:
            raise ValueError(f"未知策略类型: {stype}")

        engine = BacktestEngine(initial_cash=run.initial_cash)
        result = engine.run(df, strategy)

        equity_data = []
        for idx, val in result.equity_curve.items():
            equity_data.append({"date": str(idx), "value": round(float(val), 2)})

        import numpy as np
        from datetime import date as date_type

        class NpEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, (np.integer,)):
                    return int(obj)
                if isinstance(obj, (np.floating,)):
                    return float(obj)
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                if isinstance(obj, (pd.Timestamp, date_type)):
                    return str(obj)
                return super().default(obj)

        def safe_json(obj):
            return json.loads(json.dumps(obj, cls=NpEncoder))

        run.result_json = safe_json(result.performance)
        run.equity_curve = equity_data
        run.trades_json = safe_json(result.trades)
        run.status = "done"
    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)
    run.save()


def backtest_list(request):
    runs = BacktestRun.objects.select_related("symbol", "strategy").all()
    return render(request, "backtest/list.html", {"runs": runs})


def backtest_run(request):
    if request.method == "POST":
        symbol_id = request.POST.get("symbol_id")
        strategy_id = request.POST.get("strategy_id")
        start_date = request.POST.get("start_date", "")
        end_date = request.POST.get("end_date", "")
        initial_cash = float(request.POST.get("initial_cash", 100000))

        run = BacktestRun.objects.create(
            symbol_id=symbol_id, strategy_id=strategy_id,
            start_date=start_date, end_date=end_date,
            initial_cash=initial_cash, status="pending",
        )
        t = threading.Thread(target=_run_backtest_thread, args=(run.id,), daemon=True)
        t.start()

        messages.info(request, "回测已启动，请等待完成...")
        return redirect("backtest_detail", run_id=run.id)

    symbols = Symbol.objects.all()
    strats = Strategy.objects.all()
    return render(request, "backtest/run.html", {"symbols": symbols, "strategies": strats})


def backtest_detail(request, run_id):
    run = get_object_or_404(BacktestRun, pk=run_id)
    return render(request, "backtest/detail.html", {"run": run})


def backtest_status(request, run_id):
    run = get_object_or_404(BacktestRun, pk=run_id)
    return JsonResponse({
        "status": run.status,
        "result": run.result_json,
        "equity_curve": run.equity_curve,
        "trades": run.trades_json,
        "error": run.error_message,
    })


def backtest_compare(request):
    run_ids = request.GET.getlist("ids")
    runs = BacktestRun.objects.filter(pk__in=run_ids, status="done") if run_ids else []
    all_runs = BacktestRun.objects.filter(status="done").select_related("symbol", "strategy")

    series = []
    for r in runs:
        series.append({
            "name": f"{r.symbol.code} - {r.strategy.name}",
            "data": r.equity_curve,
        })

    return render(request, "backtest/compare.html", {
        "runs": runs, "all_runs": all_runs, "series": json.dumps(series),
    })
