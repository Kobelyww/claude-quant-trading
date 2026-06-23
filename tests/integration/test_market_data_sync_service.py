from datetime import date
from decimal import Decimal

import pytest

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.data.providers.registry import ProviderRegistry
from quant_trading.data.sync import sync_daily_market_data
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import DataSyncRunORM
from quant_trading.storage.repositories import InstrumentRepository, MarketDataRepository


class FakeProvider:
    name = "fake"

    def __init__(self, bars=None, error: Exception | None = None):
        self.bars = bars or []
        self.error = error
        self.calls = []

    def fetch_daily_bars(self, instrument_id, symbol, start, end):
        self.calls.append((instrument_id, symbol, start, end))
        if self.error is not None:
            raise self.error
        return [
            Bar(
                instrument_id=instrument_id,
                symbol=symbol,
                market=Market.A_STOCK,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source=self.name,
            )
            for bar in self.bars
        ]


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def make_bar(timestamp: date | str) -> Bar:
    return Bar(
        instrument_id=0,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=timestamp,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("1000"),
        source="fake",
    )


def test_sync_daily_market_data_upserts_instrument_bars_and_audit_row():
    engine = make_engine_with_schema()
    provider = FakeProvider([make_bar("2026-01-01"), make_bar(date(2026, 1, 2))])
    registry = ProviderRegistry([provider])

    result = sync_daily_market_data(
        engine,
        provider_name="fake",
        symbol="000001",
        start="2026-01-01",
        end="2026-01-02",
        registry=registry,
        job_run_id=5,
    )
    second = sync_daily_market_data(
        engine,
        provider_name="fake",
        symbol="000001",
        start="2026-01-01",
        end="2026-01-02",
        registry=registry,
        job_run_id=6,
    )

    assert result["provider"] == "fake"
    assert result["symbol"] == "000001"
    assert result["imported_bars"] == 2
    assert result["sync_run_id"] == 1
    assert second["sync_run_id"] == 2
    assert provider.calls[0][1:] == ("000001", "2026-01-01", "2026-01-02")

    with session_scope(engine) as session:
        instrument = InstrumentRepository(session).get_by_symbol("000001")
        bars = MarketDataRepository(session).list_bars("000001")
        sync_run = session.get(DataSyncRunORM, 1)
        assert instrument is not None
        assert instrument.exchange == "SZSE"
        assert len(bars) == 2
        assert sync_run.status == "succeeded"
        assert sync_run.job_run_id == 5


def test_sync_daily_market_data_validates_before_provider_call():
    engine = make_engine_with_schema()
    provider = FakeProvider([make_bar(date(2026, 1, 1))])
    registry = ProviderRegistry([provider])

    with pytest.raises(ValueError, match="symbol is required"):
        sync_daily_market_data(engine, "fake", "   ", None, None, registry=registry)
    with pytest.raises(ValueError, match="start_date must be before or equal to end_date"):
        sync_daily_market_data(engine, "fake", "000001", "2026-02-01", "2026-01-01", registry=registry)
    with pytest.raises(ValueError, match="invalid date"):
        sync_daily_market_data(engine, "fake", "000001", "bad-date", None, registry=registry)

    assert provider.calls == []


def test_sync_daily_market_data_marks_failed_on_provider_error():
    engine = make_engine_with_schema()
    registry = ProviderRegistry([FakeProvider(error=RuntimeError("provider unavailable"))])

    with pytest.raises(RuntimeError, match="provider unavailable"):
        sync_daily_market_data(engine, "fake", "600000", None, None, registry=registry)

    with session_scope(engine) as session:
        sync_run = session.get(DataSyncRunORM, 1)
        assert sync_run.provider == "fake"
        assert sync_run.symbol == "600000"
        assert sync_run.exchange == "SSE"
        assert sync_run.status == "failed"
        assert sync_run.error_message == "provider unavailable"
