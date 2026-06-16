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
