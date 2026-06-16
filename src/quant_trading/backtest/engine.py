from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Engine

from quant_trading.core.models import Portfolio
from quant_trading.execution.simulator import SimulatedBroker
from quant_trading.portfolio.accounting import apply_fill
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import (
    BacktestEquityPointORM,
    BacktestFillORM,
    BacktestOrderORM,
    BacktestRunORM,
)
from quant_trading.storage.repositories import MarketDataRepository
from quant_trading.strategy.base import Strategy


@dataclass(frozen=True)
class BacktestSummary:
    run_id: int
    final_equity: Decimal
    equity_points: int
    order_count: int
    fill_count: int


class BacktestEngine:
    def __init__(
        self,
        engine: Engine,
        initial_cash: Decimal,
        commission_rate: Decimal,
        slippage_rate: Decimal,
    ):
        self.engine = engine
        self.initial_cash = initial_cash
        self.broker = SimulatedBroker(
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
        )

    def run(self, symbol: str, strategy: Strategy, strategy_name: str) -> BacktestSummary:
        with session_scope(self.engine) as session:
            bars = MarketDataRepository(session).list_bars(symbol)
            run = BacktestRunORM(
                strategy_name=strategy_name,
                symbol=symbol,
                initial_cash=self.initial_cash,
                status="running",
            )
            session.add(run)
            session.flush()

            portfolio = Portfolio(account_id=run.id, cash=self.initial_cash)
            order_count = 0
            fill_count = 0

            for index in range(len(bars)):
                history = bars[: index + 1]
                latest = history[-1]
                intents = strategy.on_bar(history, portfolio)
                for intent in intents:
                    fill = self.broker.execute_market_order(intent, latest)
                    try:
                        portfolio = apply_fill(portfolio, fill)
                    except ValueError as exc:
                        if str(exc) == "insufficient cash for buy fill":
                            continue
                        raise
                    order_count += 1
                    fill_count += 1
                    session.add(
                        BacktestOrderORM(
                            run_id=run.id,
                            instrument_id=intent.instrument_id,
                            symbol=intent.symbol,
                            side=intent.side.value,
                            quantity=intent.quantity,
                            reason=intent.reason,
                            status="filled",
                            submitted_at=latest.timestamp,
                        )
                    )
                    session.add(
                        BacktestFillORM(
                            run_id=run.id,
                            instrument_id=fill.instrument_id,
                            symbol=fill.symbol,
                            side=fill.side.value,
                            quantity=fill.quantity,
                            price=fill.price,
                            commission=fill.commission,
                            slippage=fill.slippage,
                            filled_at=fill.filled_at,
                        )
                    )

                for position in portfolio.positions.values():
                    if position.instrument_id == latest.instrument_id:
                        position.market_price = latest.close
                session.add(
                    BacktestEquityPointORM(
                        run_id=run.id,
                        timestamp=latest.timestamp,
                        equity=portfolio.equity,
                        cash=portfolio.cash,
                        market_value=portfolio.market_value,
                        drawdown=portfolio.drawdown,
                    )
                )

            run.final_equity = portfolio.equity
            run.status = "done"
            return BacktestSummary(
                run_id=run.id,
                final_equity=portfolio.equity,
                equity_points=len(bars),
                order_count=order_count,
                fill_count=fill_count,
            )
