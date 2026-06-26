from datetime import date
from decimal import Decimal

from quant_trading.core.enums import Market
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import (
    InstrumentRepository,
    MarketDataRepository,
)


def test_insert_instrument_and_daily_bar_round_trip():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    with session_scope(engine) as session:
        instruments = InstrumentRepository(session)
        bars = MarketDataRepository(session)

        instrument = instruments.upsert_symbol(
            symbol="000001",
            name="平安银行",
            market=Market.A_STOCK,
            asset_type="stock",
            currency="CNY",
            exchange="SZSE",
        )
        bars.upsert_daily_bar(
            instrument_id=instrument.id,
            timestamp=date(2026, 5, 8),
            open=Decimal("10.00"),
            high=Decimal("10.50"),
            low=Decimal("9.90"),
            close=Decimal("10.20"),
            volume=Decimal("123456"),
            source="legacy_sqlite",
            adjusted="qfq",
        )

    with session_scope(engine) as session:
        loaded = MarketDataRepository(session).list_bars("000001")

    assert len(loaded) == 1
    assert loaded[0].symbol == "000001"
    assert loaded[0].close == Decimal("10.200000")


def test_market_data_repository_list_bars_filters_date_source_and_adjustment():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    with session_scope(engine) as session:
        instruments = InstrumentRepository(session)
        bars = MarketDataRepository(session)

        instrument = instruments.upsert_symbol(
            symbol="000001",
            name="平安银行",
            market=Market.A_STOCK,
            asset_type="stock",
            currency="CNY",
            exchange="SZSE",
        )
        for day, source, adjusted, close in [
            (date(2026, 1, 1), "legacy", "hfq", Decimal("10.00")),
            (date(2026, 1, 2), "akshare", "qfq", Decimal("11.00")),
            (date(2026, 1, 3), "akshare", "hfq", Decimal("12.00")),
        ]:
            bars.upsert_daily_bar(
                instrument_id=instrument.id,
                timestamp=day,
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("1000"),
                source=source,
                adjusted=adjusted,
            )

    with session_scope(engine) as session:
        repo = MarketDataRepository(session)
        all_bars = repo.list_bars("000001")
        filtered = repo.list_bars(
            "000001",
            start=date(2026, 1, 2),
            end=date(2026, 1, 2),
            source="akshare",
            adjusted="qfq",
        )

    assert [bar.timestamp.isoformat() for bar in all_bars] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert [bar.timestamp.isoformat() for bar in filtered] == ["2026-01-02"]
    assert filtered[0].source == "akshare"
    assert filtered[0].adjusted.value == "qfq"
