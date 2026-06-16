from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from quant_trading.core.enums import (
    Adjustment,
    Market,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskDecisionType,
    Timeframe,
)


def to_decimal(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class Bar:
    instrument_id: int
    symbol: str
    market: Market
    timestamp: date | datetime | str
    open: Decimal | int | float | str
    high: Decimal | int | float | str
    low: Decimal | int | float | str
    close: Decimal | int | float | str
    volume: Decimal | int | float | str
    timeframe: Timeframe = Timeframe.DAILY
    amount: Decimal | int | float | str | None = None
    adjusted: Adjustment = Adjustment.QFQ
    source: str = "legacy"

    def __post_init__(self) -> None:
        object.__setattr__(self, "open", to_decimal(self.open))
        object.__setattr__(self, "high", to_decimal(self.high))
        object.__setattr__(self, "low", to_decimal(self.low))
        object.__setattr__(self, "close", to_decimal(self.close))
        object.__setattr__(self, "volume", to_decimal(self.volume))
        if self.amount is not None:
            object.__setattr__(self, "amount", to_decimal(self.amount))
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be greater than or equal to open/close/low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be less than or equal to open/close/high")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")


@dataclass
class OrderIntent:
    instrument_id: int
    symbol: str
    side: OrderSide
    quantity: int
    reason: str
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    status: OrderStatus = OrderStatus.CREATED

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.limit_price is not None:
            self.limit_price = to_decimal(self.limit_price)


@dataclass
class Fill:
    order_id: int | None
    instrument_id: int
    symbol: str
    side: OrderSide
    quantity: int
    price: Decimal
    commission: Decimal
    slippage: Decimal
    filled_at: date | datetime | str

    @property
    def notional(self) -> Decimal:
        return self.price * Decimal(self.quantity)


@dataclass
class Position:
    instrument_id: int
    symbol: str
    quantity: int
    avg_cost: Decimal
    market_price: Decimal

    @property
    def market_value(self) -> Decimal:
        return self.market_price * Decimal(self.quantity)

    @property
    def unrealized_pnl(self) -> Decimal:
        return (self.market_price - self.avg_cost) * Decimal(self.quantity)


@dataclass
class Portfolio:
    account_id: int
    cash: Decimal
    positions: dict[int, Position] = field(default_factory=dict)
    realized_pnl: Decimal = Decimal("0")
    peak_equity: Decimal | None = None

    @property
    def market_value(self) -> Decimal:
        return sum((p.market_value for p in self.positions.values()), Decimal("0"))

    @property
    def equity(self) -> Decimal:
        return self.cash + self.market_value

    @property
    def drawdown(self) -> Decimal:
        peak = self.peak_equity or self.equity
        if peak <= 0:
            return Decimal("0")
        return (peak - self.equity) / peak


@dataclass(frozen=True)
class RiskDecision:
    decision: RiskDecisionType
    rule_name: str
    message: str
    order_intent: OrderIntent | None = None
