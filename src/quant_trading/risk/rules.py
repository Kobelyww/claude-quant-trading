from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from quant_trading.core.enums import OrderSide, RiskDecisionType, StrategyStatus
from quant_trading.core.models import Bar, OrderIntent, Portfolio, RiskDecision


class RiskRule(Protocol):
    def evaluate(
        self,
        intent: OrderIntent,
        latest_bar: Bar | None,
        portfolio: Portfolio,
        strategy_status: StrategyStatus,
    ) -> RiskDecision:
        raise NotImplementedError


class StrategyStatusRule:
    def evaluate(
        self,
        intent: OrderIntent,
        latest_bar: Bar | None,
        portfolio: Portfolio,
        strategy_status: StrategyStatus,
    ) -> RiskDecision:
        if strategy_status is not StrategyStatus.APPROVED:
            return RiskDecision(
                RiskDecisionType.REJECTED,
                self.__class__.__name__,
                "strategy is not approved",
                intent,
            )
        return RiskDecision(
            RiskDecisionType.APPROVED,
            self.__class__.__name__,
            "strategy approved",
            intent,
        )


class NoTradeWithoutDataRule:
    def evaluate(
        self,
        intent: OrderIntent,
        latest_bar: Bar | None,
        portfolio: Portfolio,
        strategy_status: StrategyStatus,
    ) -> RiskDecision:
        if latest_bar is None:
            return RiskDecision(
                RiskDecisionType.REJECTED,
                self.__class__.__name__,
                "latest market bar is missing",
                intent,
            )
        return RiskDecision(
            RiskDecisionType.APPROVED,
            self.__class__.__name__,
            "market data present",
            intent,
        )


class PriceSanityRule:
    def evaluate(
        self,
        intent: OrderIntent,
        latest_bar: Bar | None,
        portfolio: Portfolio,
        strategy_status: StrategyStatus,
    ) -> RiskDecision:
        if latest_bar is None or latest_bar.close <= 0:
            return RiskDecision(
                RiskDecisionType.REJECTED,
                self.__class__.__name__,
                "latest close price is invalid",
                intent,
            )
        return RiskDecision(
            RiskDecisionType.APPROVED,
            self.__class__.__name__,
            "price is valid",
            intent,
        )


@dataclass(frozen=True)
class MaxOrderValueRule:
    max_order_value: Decimal

    def evaluate(
        self,
        intent: OrderIntent,
        latest_bar: Bar | None,
        portfolio: Portfolio,
        strategy_status: StrategyStatus,
    ) -> RiskDecision:
        if latest_bar is None:
            return RiskDecision(
                RiskDecisionType.REJECTED,
                self.__class__.__name__,
                "latest market bar is missing",
                intent,
            )
        order_value = latest_bar.close * Decimal(intent.quantity)
        if order_value > self.max_order_value:
            return RiskDecision(
                RiskDecisionType.REJECTED,
                self.__class__.__name__,
                "order value exceeds limit",
                intent,
            )
        return RiskDecision(
            RiskDecisionType.APPROVED,
            self.__class__.__name__,
            "order value within limit",
            intent,
        )


@dataclass(frozen=True)
class MaxGrossExposureRule:
    max_gross_exposure: Decimal

    def evaluate(
        self,
        intent: OrderIntent,
        latest_bar: Bar | None,
        portfolio: Portfolio,
        strategy_status: StrategyStatus,
    ) -> RiskDecision:
        if latest_bar is None:
            return RiskDecision(
                RiskDecisionType.REJECTED,
                self.__class__.__name__,
                "latest market bar is missing",
                intent,
            )
        if portfolio.equity <= 0:
            return RiskDecision(
                RiskDecisionType.REJECTED,
                self.__class__.__name__,
                "portfolio equity must be positive",
                intent,
            )

        order_notional = latest_bar.close * Decimal(intent.quantity)
        proposed_market_value = portfolio.market_value

        if intent.side is OrderSide.BUY:
            proposed_market_value += order_notional
        else:
            existing_position = portfolio.positions.get(intent.instrument_id)
            current_position_value = (
                existing_position.market_value if existing_position is not None else Decimal("0")
            )
            reduction = min(current_position_value, order_notional)
            proposed_market_value -= reduction

        proposed_exposure = proposed_market_value / portfolio.equity
        if proposed_exposure > self.max_gross_exposure:
            return RiskDecision(
                RiskDecisionType.REJECTED,
                self.__class__.__name__,
                "gross exposure exceeds limit",
                intent,
            )
        return RiskDecision(
            RiskDecisionType.APPROVED,
            self.__class__.__name__,
            "gross exposure within limit",
            intent,
        )
