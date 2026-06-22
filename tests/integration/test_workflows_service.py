from decimal import Decimal
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from quant_trading.core.enums import CashLedgerEventType
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import CashLedgerORM, PaperRunORM
from quant_trading.workflows import (
    create_paper_account,
    import_legacy_data,
    run_ma_cross_backtest,
    run_paper_tick,
    start_ma_cross_paper_run,
)


def test_workflow_service_runs_core_local_loop(legacy_sqlite_db: Path, tmp_path: Path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow.sqlite3'}")
    create_all(engine)

    import_result = import_legacy_data(engine, legacy_sqlite_db)
    backtest_result = run_ma_cross_backtest(
        engine,
        symbol="000001",
        short_window=3,
        long_window=8,
        order_size=50,
        initial_cash=Decimal("100000"),
    )
    account_result = create_paper_account(
        engine,
        name="Core Local Loop",
        initial_cash=Decimal("100000"),
    )
    run_result = start_ma_cross_paper_run(
        engine,
        account_id=account_result["account_id"],
        symbol="000001",
        short_window=3,
        long_window=8,
        order_size=50,
    )
    tick_result = run_paper_tick(engine, run_result["run_id"])
    second_tick = run_paper_tick(engine, run_result["run_id"])

    assert import_result == {"imported_symbols": 1, "imported_bars": 121}
    assert backtest_result["symbol"] == "000001"
    assert backtest_result["strategy_name"] == "ma_cross"
    assert backtest_result["run_id"] > 0
    assert Decimal(backtest_result["final_equity"]) > Decimal("0")
    assert backtest_result["equity_points"] == 121
    assert account_result == {
        "account_id": account_result["account_id"],
        "name": "Core Local Loop",
        "initial_cash": "100000",
        "base_currency": "CNY",
    }
    assert run_result == {
        "run_id": run_result["run_id"],
        "account_id": account_result["account_id"],
        "symbol": "000001",
        "strategy_name": "ma_cross",
        "status": "running",
    }
    assert tick_result["run_id"] == run_result["run_id"]
    assert tick_result["account_id"] == account_result["account_id"]
    assert tick_result["snapshot_created"] is True
    assert tick_result["idempotent_noop"] is False
    assert second_tick["idempotent_noop"] is True
    assert second_tick["snapshot_created"] is False
    assert second_tick["orders_created"] == 0
    assert second_tick["orders_filled"] == 0
    assert second_tick["orders_rejected"] == 0
    assert second_tick["fills_created"] == 0
    assert second_tick["risk_decision_count"] == 0
    assert second_tick["processed_at"] == tick_result["processed_at"]


def test_workflow_service_persists_strategy_and_risk_config(tmp_path: Path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow-config.sqlite3'}")
    create_all(engine)

    account = create_paper_account(
        engine,
        name="Config Account",
        initial_cash=Decimal("250000"),
        base_currency="",
    )
    run = start_ma_cross_paper_run(
        engine,
        account_id=account["account_id"],
        symbol="000001",
        short_window=4,
        long_window=13,
        order_size=75,
        max_order_value=Decimal("12345.6700"),
    )

    with session_scope(engine) as session:
        paper_run = session.get(PaperRunORM, run["run_id"])
        strategy_config = json.loads(paper_run.strategy_config)
        risk_config = json.loads(paper_run.risk_config)

    assert strategy_config == {
        "strategy_name": "ma_cross",
        "short_window": 4,
        "long_window": 13,
        "order_size": 75,
    }
    assert risk_config == {"max_order_value": "12345.67"}
    assert account["base_currency"] == "CNY"


def test_workflow_service_rejects_invalid_values(tmp_path: Path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow-invalid.sqlite3'}")
    create_all(engine)

    with pytest.raises(ValueError, match="paper account name is required"):
        create_paper_account(engine, name="  ", initial_cash=Decimal("100000"))

    with pytest.raises(ValueError, match="short_window must be greater than 0"):
        run_ma_cross_backtest(
            engine,
            symbol="000001",
            short_window=0,
            long_window=8,
            order_size=50,
            initial_cash=Decimal("100000"),
        )

    with pytest.raises(ValueError, match="long_window must be greater than short_window"):
        run_ma_cross_backtest(
            engine,
            symbol="000001",
            short_window=8,
            long_window=8,
            order_size=50,
            initial_cash=Decimal("100000"),
        )

    with pytest.raises(ValueError, match="order_size must be positive"):
        run_ma_cross_backtest(
            engine,
            symbol="000001",
            short_window=3,
            long_window=8,
            order_size=0,
            initial_cash=Decimal("100000"),
        )

    with pytest.raises(ValueError, match="initial_cash must be greater than 0"):
        create_paper_account(engine, name="Invalid Cash", initial_cash=Decimal("0"))

    account = create_paper_account(
        engine,
        name="Invalid Risk Config",
        initial_cash=Decimal("100000"),
    )

    with pytest.raises(ValueError, match="max_order_value must be positive"):
        start_ma_cross_paper_run(
            engine,
            account_id=account["account_id"],
            symbol="000001",
            short_window=3,
            long_window=8,
            order_size=50,
            max_order_value=Decimal("0"),
        )


def test_workflow_service_rejects_invalid_string_boundaries(tmp_path: Path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow-string-bounds.sqlite3'}")
    create_all(engine)
    account = create_paper_account(engine, name="Boundary Account", initial_cash=Decimal("100000"))

    with pytest.raises(ValueError, match="symbol is required"):
        run_ma_cross_backtest(
            engine,
            symbol="  ",
            short_window=3,
            long_window=8,
            order_size=50,
            initial_cash=Decimal("100000"),
        )

    with pytest.raises(ValueError, match="symbol is required"):
        start_ma_cross_paper_run(
            engine,
            account_id=account["account_id"],
            symbol="  ",
            short_window=3,
            long_window=8,
            order_size=50,
        )

    with pytest.raises(ValueError, match="symbol is too long"):
        run_ma_cross_backtest(
            engine,
            symbol="1" * 33,
            short_window=3,
            long_window=8,
            order_size=50,
            initial_cash=Decimal("100000"),
        )

    with pytest.raises(ValueError, match="symbol is too long"):
        start_ma_cross_paper_run(
            engine,
            account_id=account["account_id"],
            symbol="1" * 33,
            short_window=3,
            long_window=8,
            order_size=50,
        )

    with pytest.raises(ValueError, match="name is too long"):
        create_paper_account(engine, name="A" * 129, initial_cash=Decimal("100000"))

    with pytest.raises(ValueError, match="base_currency is too long"):
        create_paper_account(
            engine,
            name="Oversized Currency",
            initial_cash=Decimal("100000"),
            base_currency="X" * 17,
        )


def test_workflow_service_strips_symbols_before_use(legacy_sqlite_db: Path, tmp_path: Path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow-strip-symbol.sqlite3'}")
    create_all(engine)
    import_legacy_data(engine, legacy_sqlite_db)
    account = create_paper_account(engine, name="Strip Symbol", initial_cash=Decimal("100000"))

    backtest = run_ma_cross_backtest(
        engine,
        symbol=" 000001 ",
        short_window=3,
        long_window=8,
        order_size=50,
        initial_cash=Decimal("100000"),
    )
    run = start_ma_cross_paper_run(
        engine,
        account_id=account["account_id"],
        symbol=" 000001 ",
        short_window=3,
        long_window=8,
        order_size=50,
    )

    with session_scope(engine) as session:
        paper_run = session.get(PaperRunORM, run["run_id"])

    assert backtest["symbol"] == "000001"
    assert run["symbol"] == "000001"
    assert paper_run.symbol == "000001"


def test_workflow_service_rejects_backtest_symbol_without_market_bars(
    legacy_sqlite_db: Path,
    tmp_path: Path,
):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow-missing-bars.sqlite3'}")
    create_all(engine)
    import_legacy_data(engine, legacy_sqlite_db)

    with pytest.raises(ValueError, match="no market bars found for symbol: NO_SUCH"):
        run_ma_cross_backtest(
            engine,
            symbol="NO_SUCH",
            short_window=3,
            long_window=8,
            order_size=50,
            initial_cash=Decimal("100000"),
        )


def test_workflow_service_rejects_non_finite_decimals(tmp_path: Path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow-decimal-bounds.sqlite3'}")
    create_all(engine)
    account = create_paper_account(engine, name="Finite Account", initial_cash=Decimal("100000"))

    with pytest.raises(ValueError, match="initial_cash must be finite"):
        create_paper_account(engine, name="NaN Cash", initial_cash=Decimal("NaN"))

    with pytest.raises(ValueError, match="initial_cash must be finite"):
        run_ma_cross_backtest(
            engine,
            symbol="000001",
            short_window=3,
            long_window=8,
            order_size=50,
            initial_cash=Decimal("Infinity"),
        )

    with pytest.raises(ValueError, match="max_order_value must be finite"):
        start_ma_cross_paper_run(
            engine,
            account_id=account["account_id"],
            symbol="000001",
            short_window=3,
            long_window=8,
            order_size=50,
            max_order_value=Decimal("NaN"),
        )

    with pytest.raises(ValueError, match="max_order_value must be finite"):
        start_ma_cross_paper_run(
            engine,
            account_id=account["account_id"],
            symbol="000001",
            short_window=3,
            long_window=8,
            order_size=50,
            max_order_value=Decimal("Infinity"),
        )


def test_create_paper_account_writes_initial_deposit_ledger(tmp_path: Path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow-ledger.sqlite3'}")
    create_all(engine)

    account = create_paper_account(
        engine,
        name="Ledger Account",
        initial_cash=Decimal("100000"),
    )

    with session_scope(engine) as session:
        ledger_rows = session.scalars(
            select(CashLedgerORM).where(CashLedgerORM.account_id == account["account_id"])
        ).all()

    assert len(ledger_rows) == 1
    assert ledger_rows[0].event_type == CashLedgerEventType.INITIAL_DEPOSIT.value
    assert ledger_rows[0].amount == Decimal("100000.000000")
    assert ledger_rows[0].cash_after == Decimal("100000.000000")
