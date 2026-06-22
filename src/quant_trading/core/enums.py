from enum import StrEnum


class Market(StrEnum):
    A_STOCK = "a_stock"
    US_STOCK = "us_stock"
    CRYPTO = "crypto"


class AssetType(StrEnum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"


class Timeframe(StrEnum):
    DAILY = "1d"


class Adjustment(StrEnum):
    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    CREATED = "created"
    RISK_CHECKED = "risk_checked"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class StrategyStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    DISABLED = "disabled"


class RiskDecisionType(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REDUCED = "reduced"
    HALTED = "halted"


class PaperRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class PaperOrderStatus(StrEnum):
    CREATED = "created"
    RISK_REJECTED = "risk_rejected"
    FILLED = "filled"
    SKIPPED = "skipped"


class CashLedgerEventType(StrEnum):
    INITIAL_DEPOSIT = "initial_deposit"
    BUY_NOTIONAL = "buy_notional"
    SELL_NOTIONAL = "sell_notional"
    COMMISSION = "commission"
    MANUAL_ADJUSTMENT = "manual_adjustment"
