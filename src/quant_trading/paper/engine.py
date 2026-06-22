from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from quant_trading.core.enums import (
    CashLedgerEventType,
    OrderSide,
    PaperRunStatus,
    RiskDecisionType,
    StrategyStatus,
)
from quant_trading.core.models import Fill
from quant_trading.execution.simulator import SimulatedBroker
from quant_trading.portfolio.accounting import apply_fill
from quant_trading.paper.repositories import PaperStateRepository
from quant_trading.risk.engine import RiskEngine
from quant_trading.storage.db import session_scope
from quant_trading.storage.repositories import MarketDataRepository
from quant_trading.strategy.base import Strategy


@dataclass(frozen=True)
class PaperTickSummary:
    run_id: int
    account_id: int
    processed_at: date
    orders_created: int
    orders_filled: int
    orders_rejected: int
    fills_created: int
    snapshot_created: bool
    risk_decision_count: int
    idempotent_noop: bool


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

    def create_account(
        self,
        name: str,
        initial_cash: Decimal | None = None,
        base_currency: str = "CNY",
    ) -> int:
        cash = initial_cash if initial_cash is not None else self.initial_cash
        with session_scope(self.engine) as session:
            account = PaperStateRepository(session).create_account(
                name=name,
                initial_cash=cash,
                base_currency=base_currency,
            )
            return account.id

    def start_run(
        self,
        account_id: int,
        symbol: str,
        strategy: Strategy,
        strategy_name: str,
        strategy_status: StrategyStatus,
        risk_config: dict | None = None,
    ) -> int:
        if strategy_status is not StrategyStatus.APPROVED:
            raise ValueError("paper run requires an approved strategy")
        if not strategy_name:
            raise ValueError("strategy_name is required")
        if getattr(strategy, "name", strategy_name) != strategy_name:
            raise ValueError("strategy_name must match strategy.name")
        with session_scope(self.engine) as session:
            repository = PaperStateRepository(session)
            repository.load_account(account_id)
            run = repository.start_run(
                account_id=account_id,
                symbol=symbol,
                strategy_name=strategy_name,
                strategy_config=self._strategy_config(strategy, strategy_name),
                risk_config=risk_config,
            )
            return run.id

    def run_one_tick(
        self, run_id: int, strategy: Strategy, strategy_status: StrategyStatus
    ) -> PaperTickSummary:
        with session_scope(self.engine) as session:
            repository = PaperStateRepository(session)
            run = repository.load_run(run_id)
            if run.status != PaperRunStatus.RUNNING.value:
                raise ValueError(f"paper run is not running: {run.id}")
            if getattr(strategy, "name", run.strategy_name) != run.strategy_name:
                raise ValueError("strategy_name must match strategy.name")
            account = repository.load_account(run.account_id)

            bars = MarketDataRepository(session).list_bars(run.symbol)
            if not bars:
                raise ValueError(f"no market bars found for symbol: {run.symbol}")

            latest = bars[-1]
            if run.last_processed_at == latest.timestamp:
                return PaperTickSummary(
                    run_id=run.id,
                    account_id=run.account_id,
                    processed_at=latest.timestamp,
                    orders_created=0,
                    orders_filled=0,
                    orders_rejected=0,
                    fills_created=0,
                    snapshot_created=False,
                    risk_decision_count=0,
                    idempotent_noop=True,
                )

            portfolio = repository.load_portfolio(run.account_id)
            latest_position = portfolio.positions.get(latest.instrument_id)
            if latest_position is not None:
                latest_position.market_price = latest.close
            orders_created = 0
            orders_filled = 0
            orders_rejected = 0
            fills_created = 0
            risk_decision_count = 0
            for intent in strategy.on_bar(bars, portfolio):
                order = repository.create_order(run, intent, latest.timestamp)
                orders_created += 1
                decision = self.risk_engine.check_order(intent, latest, portfolio, strategy_status)
                repository.record_risk_decision(run.id, order.id, decision)
                risk_decision_count += 1
                if decision.decision is not RiskDecisionType.APPROVED:
                    repository.mark_order_rejected(order, decision.decision.value)
                    orders_rejected += 1
                    continue

                fill = self.broker.execute_market_order(intent, latest)
                fill = Fill(
                    order_id=order.id,
                    instrument_id=fill.instrument_id,
                    symbol=fill.symbol,
                    side=fill.side,
                    quantity=fill.quantity,
                    price=fill.price,
                    commission=fill.commission,
                    slippage=fill.slippage,
                    filled_at=fill.filled_at,
                )
                try:
                    updated_portfolio = apply_fill(portfolio, fill)
                except ValueError as exc:
                    if str(exc) == "insufficient cash for buy fill":
                        repository.mark_order_skipped(order, decision.decision.value)
                        continue
                    raise

                persisted_fill = repository.record_fill(run, order, fill)
                fills_created += 1
                orders_filled += 1
                self._append_fill_cash_ledger(
                    repository=repository,
                    account_id=run.account_id,
                    run_id=run.id,
                    order_id=order.id,
                    fill_id=persisted_fill.id,
                    fill=fill,
                    cash_before=portfolio.cash,
                    currency=account.base_currency,
                )
                portfolio = updated_portfolio

            repository.upsert_positions(
                run.account_id,
                portfolio,
                latest.timestamp,
                realized_pnl_instrument_id=latest.instrument_id,
            )
            repository.record_snapshot(run.account_id, run.id, latest.timestamp, portfolio)
            run.last_processed_at = latest.timestamp
            session.flush()
            return PaperTickSummary(
                run_id=run.id,
                account_id=run.account_id,
                processed_at=latest.timestamp,
                orders_created=orders_created,
                orders_filled=orders_filled,
                orders_rejected=orders_rejected,
                fills_created=fills_created,
                snapshot_created=True,
                risk_decision_count=risk_decision_count,
                idempotent_noop=False,
            )

    def _append_fill_cash_ledger(
        self,
        repository: PaperStateRepository,
        account_id: int,
        run_id: int,
        order_id: int,
        fill_id: int,
        fill: Fill,
        cash_before: Decimal,
        currency: str,
    ) -> None:
        if fill.side is OrderSide.BUY:
            notional_amount = -fill.notional
            cash_after_notional = cash_before + notional_amount
            commission_amount = -fill.commission
        else:
            notional_amount = fill.notional
            cash_after_notional = cash_before + notional_amount
            commission_amount = -fill.commission

        repository.append_cash_ledger(
            account_id=account_id,
            run_id=run_id,
            order_id=order_id,
            fill_id=fill_id,
            event_type=(
                CashLedgerEventType.BUY_NOTIONAL
                if fill.side is OrderSide.BUY
                else CashLedgerEventType.SELL_NOTIONAL
            ),
            amount=notional_amount,
            cash_after=cash_after_notional,
            currency=currency,
            occurred_at=fill.filled_at,
        )

        repository.append_cash_ledger(
            account_id=account_id,
            run_id=run_id,
            order_id=order_id,
            fill_id=fill_id,
            event_type=CashLedgerEventType.COMMISSION,
            amount=commission_amount,
            cash_after=cash_after_notional + commission_amount,
            currency=currency,
            occurred_at=fill.filled_at,
        )

    def _strategy_config(self, strategy: Strategy, strategy_name: str) -> dict:
        config = {"strategy_name": strategy_name}
        if strategy_name == "ma_cross":
            config.update(
                {
                    "short_window": strategy.short_window,
                    "long_window": strategy.long_window,
                    "order_size": strategy.order_size,
                }
            )
        return config
