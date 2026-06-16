import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine

from quant_trading.core.enums import Market
from quant_trading.storage.db import session_scope
from quant_trading.storage.repositories import (
    InstrumentRepository,
    MarketDataRepository,
)


@dataclass(frozen=True)
class LegacyImportResult:
    imported_symbols: int
    imported_bars: int


def import_legacy_sqlite(db_path: Path, engine: Engine) -> LegacyImportResult:
    if not db_path.exists():
        raise FileNotFoundError(f"legacy sqlite database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    symbols = conn.execute(
        "select id, code, name, market from data_center_symbol order by id"
    ).fetchall()

    imported_symbols = 0
    imported_bars = 0
    with session_scope(engine) as session:
        instruments = InstrumentRepository(session)
        bars_repo = MarketDataRepository(session)
        for sym in symbols:
            market = Market(sym["market"])
            exchange = "SZSE" if str(sym["code"]).startswith(("0", "3")) else "SSE"
            instrument = instruments.upsert_symbol(
                symbol=sym["code"],
                name=sym["name"] or "",
                market=market,
                asset_type="stock",
                currency="CNY" if market is Market.A_STOCK else "USD",
                exchange=exchange,
            )
            imported_symbols += 1
            rows = conn.execute(
                """
                select date, open, high, low, close, volume
                from data_center_marketdata
                where symbol_id = ?
                order by date
                """,
                (sym["id"],),
            ).fetchall()
            for row in rows:
                bars_repo.upsert_daily_bar(
                    instrument_id=instrument.id,
                    timestamp=date.fromisoformat(row["date"]),
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    volume=Decimal(str(row["volume"])),
                    source="legacy_sqlite",
                    adjusted="qfq",
                )
                imported_bars += 1

    conn.close()
    return LegacyImportResult(
        imported_symbols=imported_symbols,
        imported_bars=imported_bars,
    )
