from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Engine

from quant_trading.core.enums import RiskDecisionType, StrategyStatus
from quant_trading.core.models import Portfolio
from quant_trading.execution.simulator import SimulatedBroker
from quant_trading.portfolio.accounting import apply_fill
from quant_trading.risk.engine import RiskEngine
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import PaperAccountORM, PortfolioSnapshotORM, RiskDecisionORM
from quant_trading.storage.repositories import MarketDataRepository
from quant_trading.strategy.base import Strategy


@dataclass(frozen=True)
class PaperTickSummary:
    account_id: int
    snapshot_count: int
    risk_decision_count: int


class PaperTradingEngine:
    def __init__(
        self,
        engine: Engine,
        initial_cash: Decimal,
        risk_engine: RiskEngine,
        commission_rate: Decimal = Decimal("0.0003"),
        slippage_rate: Decimal = Decimal("0.001"),
    ):
        self.engine = engine
        self.initial_cash = initial_cash
        self.risk_engine = risk_engine
        self.broker = SimulatedBroker(commission_rate=commission_rate, slippage_rate=slippage_rate)

    def run_one_tick(
        self, symbol: str, strategy: Strategy, strategy_status: StrategyStatus
    ) -> PaperTickSummary:
        with session_scope(self.engine) as session:
            account = PaperAccountORM(initial_cash=self.initial_cash)
            session.add(account)
            session.flush()

            bars = MarketDataRepository(session).list_bars(symbol)
            if not bars:
                raise ValueError(f"no market bars found for symbol: {symbol}")

            latest = bars[-1]
            portfolio = Portfolio(account_id=account.id, cash=self.initial_cash)
            risk_decision_count = 0
            for intent in strategy.on_bar(bars, portfolio):
                decision = self.risk_engine.check_order(intent, latest, portfolio, strategy_status)
                session.add(
                    RiskDecisionORM(
                        run_id=account.id,
                        decision=decision.decision.value,
                        rule_name=decision.rule_name,
                        message=decision.message,
                    )
                )
                risk_decision_count += 1
                if decision.decision is RiskDecisionType.APPROVED:
                    fill = self.broker.execute_market_order(intent, latest)
                    try:
                        portfolio = apply_fill(portfolio, fill)
                    except ValueError as exc:
                        if str(exc) == "insufficient cash for buy fill":
                            continue
                        raise

            session.add(
                PortfolioSnapshotORM(
                    account_id=account.id,
                    timestamp=latest.timestamp,
                    equity=portfolio.equity,
                    cash=portfolio.cash,
                    market_value=portfolio.market_value,
                    realized_pnl=portfolio.realized_pnl,
                    unrealized_pnl=sum(
                        (position.unrealized_pnl for position in portfolio.positions.values()),
                        Decimal("0"),
                    ),
                    drawdown=portfolio.drawdown,
                )
            )
            return PaperTickSummary(
                account_id=account.id,
                snapshot_count=1,
                risk_decision_count=risk_decision_count,
            )
