from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from quant_trading.core.enums import OrderSide, StrategyStatus
from quant_trading.core.models import OrderIntent
from quant_trading.paper.engine import PaperTradingEngine
from quant_trading.risk.engine import RiskEngine
from quant_trading.risk.rules import MaxOrderValueRule, NoTradeWithoutDataRule, PriceSanityRule, StrategyStatusRule
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import PortfolioSnapshotORM, RiskDecisionORM


class OneShotBuyStrategy:
    name = "one_shot_buy"

    def on_bar(self, bars, portfolio):
        latest = bars[-1]
        return [
            OrderIntent(
                instrument_id=latest.instrument_id,
                symbol=latest.symbol,
                side=OrderSide.BUY,
                quantity=100,
                reason="paper_tick_entry",
            )
        ]


def test_paper_tick_persists_snapshot_and_risk_decision(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)

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
        strategy=OneShotBuyStrategy(),
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
    assert result.risk_decision_count == 1
    assert len(snapshots) == 1
    assert risk_decisions[0].decision == "approved"
    assert snapshots[0].cash < Decimal("100000")
    assert snapshots[0].market_value > Decimal("0")
