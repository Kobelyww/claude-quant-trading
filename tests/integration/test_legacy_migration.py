from pathlib import Path
import sqlite3
from datetime import date, timedelta

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.repositories import (
    InstrumentRepository,
    MarketDataRepository,
)


def _build_legacy_sample(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            create table data_center_symbol (
                id integer primary key,
                code text not null unique,
                name text,
                market text not null
            );

            create table data_center_marketdata (
                id integer primary key,
                symbol_id integer not null,
                date text not null,
                open real not null,
                high real not null,
                low real not null,
                close real not null,
                volume real not null
            );
            """
        )
        conn.execute(
            """
            insert into data_center_symbol (id, code, name, market)
            values (?, ?, ?, ?)
            """,
            (1, "000001", "平安银行", "a_stock"),
        )
        start = date(2026, 1, 1)
        rows = []
        for offset in range(121):
            current = start + timedelta(days=offset)
            delta = offset / 100
            rows.append(
                (
                    1,
                    current.isoformat(),
                    10.0 + delta,
                    10.5 + delta,
                    9.9 + delta,
                    10.2 + delta,
                    100000 + offset,
                )
            )
        conn.executemany(
            """
            insert into data_center_marketdata (
                symbol_id,
                date,
                open,
                high,
                low,
                close,
                volume
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _needs_sample_rebuild(db_path: Path) -> bool:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return True

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type='table'"
            ).fetchall()
        }
        if {"data_center_symbol", "data_center_marketdata"} - tables:
            return True
        for (value,) in conn.execute(
            "select date from data_center_marketdata order by date limit 200"
        ).fetchall():
            date.fromisoformat(value)
        return False
    except Exception:
        return True
    finally:
        conn.close()


def test_import_existing_legacy_sqlite_sample():
    legacy_db = Path("django_app/db.sqlite3")
    assert legacy_db.exists()
    if _needs_sample_rebuild(legacy_db):
        _build_legacy_sample(legacy_db)

    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    result = import_legacy_sqlite(legacy_db, engine)

    assert result.imported_symbols >= 1
    assert result.imported_bars >= 100

    with session_scope(engine) as session:
        instrument = InstrumentRepository(session).get_by_symbol("000001")
        bars = MarketDataRepository(session).list_bars("000001")

    assert instrument is not None
    assert instrument.name == "平安银行"
    assert len(bars) >= 100
