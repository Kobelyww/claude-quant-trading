class QuantTradingError(Exception):
    """Base exception for quant trading platform errors."""


class DataValidationError(QuantTradingError):
    """Raised when market data is missing or invalid."""


class RiskRejectedError(QuantTradingError):
    """Raised when a risk rule rejects an order."""
