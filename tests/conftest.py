from datetime import date, timedelta
from pathlib import Path
import sqlite3

import pytest


def build_legacy_sample(db_path: Path) -> None:
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


@pytest.fixture
def legacy_sqlite_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "legacy.sqlite3"
    build_legacy_sample(db_path)
    return db_path
