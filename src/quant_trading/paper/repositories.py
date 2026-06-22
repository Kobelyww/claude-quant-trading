from datetime import date, datetime
from decimal import Decimal
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_trading.core.enums import CashLedgerEventType, PaperOrderStatus, PaperRunStatus
from quant_trading.core.models import Fill, OrderIntent, Portfolio, Position, RiskDecision
from quant_trading.storage.models import (
    CashLedgerORM,
    PaperAccountORM,
    PaperFillORM,
    PaperOrderORM,
    PaperPositionORM,
    PaperRunORM,
    PortfolioSnapshotORM,
    RiskDecisionORM,
)


def _json_dumps(value: dict) -> str:
    def default(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=default)


class PaperStateRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_account(self, name: str, initial_cash: Decimal, base_currency: str) -> PaperAccountORM:
        account = PaperAccountORM(
            name=name,
            base_currency=base_currency,
            initial_cash=initial_cash,
            status="active",
        )
        self.session.add(account)
        self.session.flush()
        self.session.add(
            CashLedgerORM(
                account_id=account.id,
                run_id=None,
                order_id=None,
                fill_id=None,
                event_type=CashLedgerEventType.INITIAL_DEPOSIT.value,
                amount=initial_cash,
                cash_after=initial_cash,
                currency=base_currency,
                occurred_at=date.today(),
            )
        )
        self.session.flush()
        return account

    def start_run(
        self,
        account_id: int,
        symbol: str,
        strategy_name: str,
        risk_config: dict | None,
    ) -> PaperRunORM:
        run = PaperRunORM(
            account_id=account_id,
            strategy_name=strategy_name,
            symbol=symbol,
            universe_config=_json_dumps({"symbols": [symbol]}),
            strategy_config=_json_dumps({"strategy_name": strategy_name}),
            risk_config=_json_dumps(risk_config or {}),
            status=PaperRunStatus.RUNNING.value,
            started_at=datetime.utcnow(),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def load_run(self, run_id: int) -> PaperRunORM:
        run = self.session.scalar(self.load_run_statement(run_id))
        if run is None:
            raise ValueError(f"paper run not found: {run_id}")
        return run

    @staticmethod
    def load_run_statement(run_id: int):
        return select(PaperRunORM).where(PaperRunORM.id == run_id).with_for_update()

    def latest_cash(self, account_id: int) -> Decimal:
        row = self.session.scalar(
            select(CashLedgerORM)
            .where(CashLedgerORM.account_id == account_id)
            .order_by(CashLedgerORM.id.desc())
        )
        if row is None:
            raise ValueError(f"cash ledger is missing for account: {account_id}")
        return row.cash_after

    def load_portfolio(self, account_id: int) -> Portfolio:
        positions = self.session.scalars(
            select(PaperPositionORM).where(PaperPositionORM.account_id == account_id)
        ).all()
        return Portfolio(
            account_id=account_id,
            cash=self.latest_cash(account_id),
            positions={
                row.instrument_id: Position(
                    instrument_id=row.instrument_id,
                    symbol=row.symbol,
                    quantity=row.quantity,
                    avg_cost=row.avg_cost,
                    market_price=row.market_price,
                )
                for row in positions
                if row.quantity != 0
            },
            realized_pnl=sum((row.realized_pnl for row in positions), Decimal("0")),
        )

    def create_order(self, run: PaperRunORM, intent: OrderIntent, submitted_at: date) -> PaperOrderORM:
        order = PaperOrderORM(
            run_id=run.id,
            account_id=run.account_id,
            instrument_id=intent.instrument_id,
            symbol=intent.symbol,
            side=intent.side.value,
            order_type=intent.order_type.value,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            reason=intent.reason,
            status=PaperOrderStatus.CREATED.value,
            submitted_at=submitted_at,
        )
        self.session.add(order)
        self.session.flush()
        return order

    def record_risk_decision(
        self, run_id: int, order_id: int, decision: RiskDecision
    ) -> RiskDecisionORM:
        row = RiskDecisionORM(
            run_id=run_id,
            order_id=order_id,
            decision=decision.decision.value,
            rule_name=decision.rule_name,
            message=decision.message,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_order_rejected(self, order: PaperOrderORM, risk_decision: str) -> PaperOrderORM:
        order.status = PaperOrderStatus.RISK_REJECTED.value
        order.risk_decision = risk_decision
        self.session.flush()
        return order

    def mark_order_skipped(self, order: PaperOrderORM, risk_decision: str) -> PaperOrderORM:
        order.status = PaperOrderStatus.SKIPPED.value
        order.risk_decision = risk_decision
        self.session.flush()
        return order

    def record_fill(self, run: PaperRunORM, order: PaperOrderORM, fill: Fill) -> PaperFillORM:
        row = PaperFillORM(
            run_id=run.id,
            account_id=run.account_id,
            order_id=order.id,
            instrument_id=fill.instrument_id,
            symbol=fill.symbol,
            side=fill.side.value,
            quantity=fill.quantity,
            price=fill.price,
            commission=fill.commission,
            slippage=fill.slippage,
            filled_at=fill.filled_at,
        )
        self.session.add(row)
        order.status = PaperOrderStatus.FILLED.value
        order.risk_decision = order.risk_decision or "approved"
        self.session.flush()
        return row

    def append_cash_ledger(
        self,
        account_id: int,
        run_id: int,
        order_id: int,
        fill_id: int,
        event_type: CashLedgerEventType,
        amount: Decimal,
        cash_after: Decimal,
        currency: str,
        occurred_at: date,
    ) -> CashLedgerORM:
        row = CashLedgerORM(
            account_id=account_id,
            run_id=run_id,
            order_id=order_id,
            fill_id=fill_id,
            event_type=event_type.value,
            amount=amount,
            cash_after=cash_after,
            currency=currency,
            occurred_at=occurred_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def upsert_positions(
        self,
        account_id: int,
        portfolio: Portfolio,
        updated_at: date,
        realized_pnl_instrument_id: int | None = None,
    ) -> None:
        existing_rows = {
            row.instrument_id: row
            for row in self.session.scalars(
                select(PaperPositionORM).where(PaperPositionORM.account_id == account_id)
            ).all()
        }
        active_position_ids = set(portfolio.positions)
        existing_realized_pnl = sum(
            (row.realized_pnl for row in existing_rows.values()), Decimal("0")
        )
        realized_pnl_delta = portfolio.realized_pnl - existing_realized_pnl
        for position in portfolio.positions.values():
            existing = existing_rows.get(position.instrument_id)
            realized_pnl = (
                Decimal("0")
                if existing is None
                else existing.realized_pnl
            )
            if position.instrument_id == realized_pnl_instrument_id:
                realized_pnl += realized_pnl_delta
            if existing is None:
                self.session.add(
                    PaperPositionORM(
                        account_id=account_id,
                        instrument_id=position.instrument_id,
                        symbol=position.symbol,
                        quantity=position.quantity,
                        avg_cost=position.avg_cost,
                        market_price=position.market_price,
                        realized_pnl=realized_pnl,
                        updated_at=updated_at,
                    )
                )
                continue
            existing.symbol = position.symbol
            existing.quantity = position.quantity
            existing.avg_cost = position.avg_cost
            existing.market_price = position.market_price
            existing.realized_pnl = realized_pnl
            existing.updated_at = updated_at

        for instrument_id, existing in existing_rows.items():
            if instrument_id in active_position_ids:
                continue
            existing.quantity = 0
            existing.market_price = Decimal("0")
            if instrument_id == realized_pnl_instrument_id:
                existing.realized_pnl += realized_pnl_delta
            existing.updated_at = updated_at

        self.session.flush()

    def record_snapshot(
        self,
        account_id: int,
        timestamp: date,
        portfolio: Portfolio,
    ) -> PortfolioSnapshotORM:
        row = PortfolioSnapshotORM(
            account_id=account_id,
            timestamp=timestamp,
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
        self.session.add(row)
        self.session.flush()
        return row
