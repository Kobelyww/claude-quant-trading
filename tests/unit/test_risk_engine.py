from datetime import date
from decimal import Decimal

from quant_trading.core.enums import Market, OrderSide, RiskDecisionType, StrategyStatus
from quant_trading.core.models import Bar, OrderIntent, Portfolio, Position
from quant_trading.risk.engine import RiskEngine
from quant_trading.risk.rules import (
    MaxGrossExposureRule,
    MaxOrderValueRule,
    NoTradeWithoutDataRule,
    PriceSanityRule,
    StrategyStatusRule,
)


def make_bar(close: str = "10") -> Bar:
    price = Decimal(close)
    return Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=date(2026, 5, 8),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("100000"),
    )


def test_risk_rejects_unapproved_strategy():
    engine = RiskEngine([StrategyStatusRule()])
    intent = OrderIntent(1, "000001", OrderSide.BUY, 100, "test")
    decision = engine.check_order(
        intent=intent,
        latest_bar=make_bar(),
        portfolio=Portfolio(account_id=1, cash=Decimal("100000")),
        strategy_status=StrategyStatus.DRAFT,
    )

    assert decision.decision is RiskDecisionType.REJECTED
    assert decision.rule_name == "StrategyStatusRule"


def test_risk_approves_valid_order():
    engine = RiskEngine([
        StrategyStatusRule(),
        NoTradeWithoutDataRule(),
        PriceSanityRule(),
        MaxOrderValueRule(max_order_value=Decimal("5000")),
        MaxGrossExposureRule(max_gross_exposure=Decimal("0.95")),
    ])
    intent = OrderIntent(1, "000001", OrderSide.BUY, 100, "test")
    decision = engine.check_order(
        intent=intent,
        latest_bar=make_bar(),
        portfolio=Portfolio(account_id=1, cash=Decimal("100000")),
        strategy_status=StrategyStatus.APPROVED,
    )

    assert decision.decision is RiskDecisionType.APPROVED


def test_max_gross_exposure_rule_allows_sell_that_reduces_existing_position():
    engine = RiskEngine([MaxGrossExposureRule(max_gross_exposure=Decimal("0.50"))])
    intent = OrderIntent(1, "000001", OrderSide.SELL, 100, "reduce risk")
    portfolio = Portfolio(
        account_id=1,
        cash=Decimal("40"),
        positions={
            1: Position(
                instrument_id=1,
                symbol="000001",
                quantity=100,
                avg_cost=Decimal("10"),
                market_price=Decimal("10"),
            )
        },
    )

    decision = engine.check_order(
        intent=intent,
        latest_bar=make_bar(),
        portfolio=portfolio,
        strategy_status=StrategyStatus.APPROVED,
    )

    assert decision.decision is RiskDecisionType.APPROVED


def test_max_gross_exposure_rule_rejects_non_positive_equity():
    engine = RiskEngine([MaxGrossExposureRule(max_gross_exposure=Decimal("0.50"))])
    intent = OrderIntent(1, "000001", OrderSide.BUY, 100, "test")
    portfolio = Portfolio(account_id=1, cash=Decimal("0"))

    decision = engine.check_order(
        intent=intent,
        latest_bar=make_bar(),
        portfolio=portfolio,
        strategy_status=StrategyStatus.APPROVED,
    )

    assert decision.decision is RiskDecisionType.REJECTED
    assert decision.rule_name == "MaxGrossExposureRule"
    assert decision.message == "portfolio equity must be positive"
