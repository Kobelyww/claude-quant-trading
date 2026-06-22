from datetime import date, datetime
from decimal import Decimal
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_trading.core.enums import CashLedgerEventType, PaperRunStatus
from quant_trading.core.models import Portfolio, Position
from quant_trading.storage.models import (
    CashLedgerORM,
    PaperAccountORM,
    PaperPositionORM,
    PaperRunORM,
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
        run = self.session.get(PaperRunORM, run_id)
        if run is None:
            raise ValueError(f"paper run not found: {run_id}")
        return run

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
