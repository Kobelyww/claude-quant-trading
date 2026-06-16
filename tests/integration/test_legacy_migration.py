from pathlib import Path

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.repositories import (
    InstrumentRepository,
    MarketDataRepository,
)


def test_import_existing_legacy_sqlite_sample(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    result = import_legacy_sqlite(legacy_sqlite_db, engine)

    assert result.imported_symbols >= 1
    assert result.imported_bars >= 100

    with session_scope(engine) as session:
        instrument = InstrumentRepository(session).get_by_symbol("000001")
        bars = MarketDataRepository(session).list_bars("000001")

    assert instrument is not None
    assert instrument.name == "平安银行"
    assert len(bars) >= 100
