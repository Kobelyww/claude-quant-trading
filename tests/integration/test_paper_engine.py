from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from quant_trading.core.enums import StrategyStatus
from quant_trading.paper.engine import PaperTradingEngine
from quant_trading.risk.engine import RiskEngine
from quant_trading.risk.rules import MaxOrderValueRule, NoTradeWithoutDataRule, PriceSanityRule, StrategyStatusRule
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import PortfolioSnapshotORM, RiskDecisionORM
from quant_trading.strategy.builtin.ma_cross import MACrossStrategy
from tests.integration.test_legacy_migration import _build_legacy_sample


def test_paper_tick_persists_snapshot_and_risk_decision(tmp_path: Path):
    legacy_db = tmp_path / "legacy.sqlite3"
    _build_legacy_sample(legacy_db)
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_db, engine)

    paper = PaperTradingEngine(
        engine=engine,
        initial_cash=Decimal("100000"),
        risk_engine=RiskEngine(
            [
                StrategyStatusRule(),
                NoTradeWithoutDataRule(),
                PriceSanityRule(),
                MaxOrderValueRule(max_order_value=Decimal("100000")),
            ]
        ),
    )
    result = paper.run_one_tick(
        symbol="000001",
        strategy=MACrossStrategy(short_window=5, long_window=20, order_size=100),
        strategy_status=StrategyStatus.APPROVED,
    )

    with session_scope(engine) as session:
        snapshots = session.scalars(
            select(PortfolioSnapshotORM).where(PortfolioSnapshotORM.account_id == result.account_id)
        ).all()
        risk_decisions = session.scalars(
            select(RiskDecisionORM).where(RiskDecisionORM.run_id == result.account_id)
        ).all()

    assert result.account_id > 0
    assert result.snapshot_count == 1
    assert result.risk_decision_count == len(risk_decisions)
    assert len(snapshots) == 1
