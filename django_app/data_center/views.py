from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from .models import Symbol, MarketData
from scripts.data_fetcher import DataFetcher


def symbol_list(request):
    symbols = Symbol.objects.all()
    for sym in symbols:
        sym._data_count = sym.marketdata_set.count()
    return render(request, "data_center/list.html", {"symbols": symbols})


def symbol_add(request):
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        name = request.POST.get("name", "").strip()
        market = request.POST.get("market", "auto")

        if not code:
            messages.error(request, "请输入标的代码")
            return redirect("data_list")

        if Symbol.objects.filter(code=code).exists():
            messages.warning(request, f"标的 {code} 已存在")
            return redirect("data_list")

        fetcher = DataFetcher()
        if market == "auto":
            market = fetcher.detect_market(code)

        Symbol.objects.create(code=code, name=name, market=market)
        messages.success(request, f"已添加 {code}")
        return redirect("data_list")

    return render(request, "data_center/add.html")


def symbol_fetch(request, symbol_id):
    symbol = get_object_or_404(Symbol, pk=symbol_id)

    if request.method == "POST":
        start = request.POST.get("start_date", "")
        end = request.POST.get("end_date", "")

        try:
            fetcher = DataFetcher()
            df = fetcher.fetch(symbol.code, start=start or None, end=end or None, market=symbol.market)

            MarketData.objects.filter(symbol=symbol).delete()
            batch = []
            for idx, row in df.iterrows():
                batch.append(MarketData(
                    symbol=symbol,
                    date=idx.date() if hasattr(idx, "date") else idx,
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                ))
            MarketData.objects.bulk_create(batch, batch_size=500)
            messages.success(request, f"成功拉取 {symbol.code} 的 {len(batch)} 条数据")
            return redirect("data_list")
        except Exception as e:
            messages.error(request, f"拉取失败: {str(e)}")
            return redirect("data_list")

    data_count = symbol.marketdata_set.count()
    date_range = symbol.date_range if data_count > 0 else (None, None)
    return render(request, "data_center/fetch.html", {
        "symbol": symbol, "data_count": data_count,
        "date_first": date_range[0], "date_last": date_range[1],
    })


def symbol_chart(request, symbol_id):
    symbol = get_object_or_404(Symbol, pk=symbol_id)
    data = list(symbol.marketdata_set.values("date", "open", "high", "low", "close", "volume"))
    return JsonResponse({"symbol": symbol.code, "market": symbol.market, "data": data})


def symbol_delete(request, symbol_id):
    symbol = get_object_or_404(Symbol, pk=symbol_id)
    code = symbol.code
    symbol.delete()
    messages.success(request, f"已删除 {code}")
    return redirect("data_list")
