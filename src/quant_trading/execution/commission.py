from decimal import Decimal


def percent_commission(notional: Decimal, rate: Decimal) -> Decimal:
    return notional * rate
