"""多市场数据获取统一接口

支持:
- A股 (akshare)
- 美股 (yfinance)
- 加密货币 (ccxt)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Literal

MarketType = Literal["a_stock", "us_stock", "crypto"]


class DataFetcher:
    """多市场数据获取器"""

    def __init__(self):
        self._ak = None
        self._yf = None
        self._ccxt = None

    def _get_akshare(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def _get_yfinance(self):
        if self._yf is None:
            import yfinance as yf
            self._yf = yf
        return self._yf

    def _get_ccxt(self):
        if self._ccxt is None:
            import ccxt
            self._ccxt = ccxt
        return self._ccxt

    def detect_market(self, symbol: str) -> MarketType:
        """自动检测标的所属市场"""
        symbol_upper = symbol.upper()
        if symbol.isdigit() and len(symbol) == 6:
            return "a_stock"
        if symbol_upper.endswith(("-USD", "-USDT", "USDT", "BTC", "ETH")):
            return "crypto"
        return "us_stock"

    def fetch(self, symbol: str, start: Optional[str] = None,
              end: Optional[str] = None, market: Optional[MarketType] = None,
              period: str = "daily") -> pd.DataFrame:
        """获取历史行情数据

        Args:
            symbol: 标的代码 (如 '000001', 'AAPL', 'BTC/USDT')
            start: 开始日期 'YYYYMMDD' 或 'YYYY-MM-DD'
            end: 结束日期
            market: 市场类型，None 则自动检测
            period: K线周期 'daily' | 'weekly' | 'monthly'

        Returns:
            DataFrame 统一格式:
                date, open, high, low, close, volume, symbol
        """
        if market is None:
            market = self.detect_market(symbol)

        if market == "a_stock":
            return self._fetch_a_stock(symbol, start, end, period)
        elif market == "us_stock":
            return self._fetch_us_stock(symbol, start, end, period)
        elif market == "crypto":
            return self._fetch_crypto(symbol, start, end, period)
        else:
            raise ValueError(f"Unknown market: {market}")

    def _parse_dates(self, start: Optional[str], end: Optional[str]) -> tuple:
        """标准化日期格式"""
        fmt = "%Y%m%d" if (start and len(start) == 8) else "%Y-%m-%d"
        s = pd.to_datetime(start, format=fmt) if start else datetime.now() - timedelta(days=365)
        e = pd.to_datetime(end, format=fmt) if end else datetime.now()
        return s, e

    def _normalize_columns(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """统一列名和格式"""
        col_map = {
            "open": "open", "Open": "open",
            "high": "high", "High": "high",
            "low": "low", "Low": "low",
            "close": "close", "Close": "close",
            "volume": "volume", "Volume": "volume",
        }
        df = df.rename(columns=col_map)
        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                df[col] = np.nan
        df["symbol"] = symbol
        df = df[["open", "high", "low", "close", "volume", "symbol"]]
        if df.index.name != "date" and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        return df.sort_index()

    def _fetch_a_stock(self, symbol: str, start: Optional[str],
                       end: Optional[str], period: str) -> pd.DataFrame:
        ak = self._get_akshare()
        s, e = self._parse_dates(start, end)
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=s.strftime("%Y%m%d"),
            end_date=e.strftime("%Y%m%d"),
            adjust="qfq",
        )
        col_map = {"开盘": "open", "最高": "high", "最低": "low",
                   "收盘": "close", "成交量": "volume", "日期": "date"}
        df = df.rename(columns=col_map)
        df["date"] = pd.to_datetime(df["日期"])
        df = df.set_index("date")
        return self._normalize_columns(df, symbol)

    def _fetch_us_stock(self, symbol: str, start: Optional[str],
                        end: Optional[str], period: str) -> pd.DataFrame:
        yf = self._get_yfinance()
        s, e = self._parse_dates(start, end)
        ticker = yf.Ticker(symbol)
        interval_map = {"daily": "1d", "weekly": "1wk", "monthly": "1mo"}
        df = ticker.history(start=s, end=e, interval=interval_map.get(period, "1d"))
        return self._normalize_columns(df, symbol)

    def _fetch_crypto(self, symbol: str, start: Optional[str],
                      end: Optional[str], period: str) -> pd.DataFrame:
        ccxt = self._get_ccxt()
        s, e = self._parse_dates(start, end)
        exchange = ccxt.binance()
        if "/" not in symbol:
            symbol = f"{symbol}/USDT"

        timeframe_map = {"daily": "1d", "weekly": "1w", "monthly": "1M"}
        ohlcv = exchange.fetch_ohlcv(
            symbol, timeframe=timeframe_map.get(period, "1d"),
            since=int(s.timestamp() * 1000),
            limit=1000,
        )
        df = pd.DataFrame(ohlcv, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"], unit="ms")
        df = df.set_index("date")
        df = df[df.index <= pd.Timestamp(e)]
        return self._normalize_columns(df, symbol)

    def fetch_multiple(self, symbols: list, start: Optional[str] = None,
                       end: Optional[str] = None) -> dict:
        """批量获取多个标的的数据"""
        results = {}
        for sym in symbols:
            try:
                results[sym] = self.fetch(sym, start, end)
            except Exception as e:
                print(f"Error fetching {sym}: {e}")
        return results
