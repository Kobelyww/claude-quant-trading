from decimal import Decimal


def total_return(initial_equity: Decimal, final_equity: Decimal) -> Decimal:
    if initial_equity == 0:
        return Decimal("0")
    return (final_equity / initial_equity) - Decimal("1")
