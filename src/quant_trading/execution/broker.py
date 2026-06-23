from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from quant_trading.core.enums import OrderSide, OrderStatus, OrderType
from quant_trading.core.models import Bar, Fill, OrderIntent


class BrokerExecutionMode(StrEnum):
    SIMULATED = "simulated"
    DRY_RUN = "dry_run"
    LIVE = "live"


class TradingDisabledError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrokerOrderRequest:
    client_order_id: str
    instrument_id: int
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: Decimal | None
    submitted_at: date | datetime | str
    reason: str

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True)
class BrokerOrderResult:
    broker_order_id: str
    status: OrderStatus
    mode: BrokerExecutionMode
    accepted: bool
    message: str
    fill: Fill | None = None


class BrokerAdapter(Protocol):
    mode: BrokerExecutionMode

    def submit_order(
        self,
        request: BrokerOrderRequest,
        market_bar: Bar | None = None,
    ) -> BrokerOrderResult:
        ...

    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        ...


@dataclass
class DryRunBrokerAdapter:
    submitted_requests: list[BrokerOrderRequest] = field(default_factory=list)
    mode: BrokerExecutionMode = BrokerExecutionMode.DRY_RUN

    def submit_order(
        self,
        request: BrokerOrderRequest,
        market_bar: Bar | None = None,
    ) -> BrokerOrderResult:
        self.submitted_requests.append(request)
        return BrokerOrderResult(
            broker_order_id=f"dry-run-{request.client_order_id}",
            status=OrderStatus.SUBMITTED,
            mode=self.mode,
            accepted=True,
            message="dry-run order accepted; no external order was placed",
        )

    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        known_ids = {f"dry-run-{request.client_order_id}" for request in self.submitted_requests}
        if broker_order_id in known_ids:
            return BrokerOrderResult(
                broker_order_id=broker_order_id,
                status=OrderStatus.CANCELLED,
                mode=self.mode,
                accepted=True,
                message="dry-run order cancelled",
            )
        return BrokerOrderResult(
            broker_order_id=broker_order_id,
            status=OrderStatus.REJECTED,
            mode=self.mode,
            accepted=False,
            message="dry-run order not found",
        )


def broker_order_request_from_intent(
    intent: OrderIntent,
    market_bar: Bar,
    client_order_id: str,
) -> BrokerOrderRequest:
    return BrokerOrderRequest(
        client_order_id=client_order_id,
        instrument_id=intent.instrument_id,
        symbol=intent.symbol,
        side=intent.side,
        order_type=intent.order_type,
        quantity=intent.quantity,
        limit_price=intent.limit_price,
        submitted_at=market_bar.timestamp,
        reason=intent.reason,
    )


def ensure_trading_enabled(
    trading_enabled: bool,
    adapter_mode: BrokerExecutionMode | str,
) -> None:
    mode = BrokerExecutionMode(adapter_mode)
    if mode is BrokerExecutionMode.LIVE and not trading_enabled:
        raise TradingDisabledError("live trading is disabled")
