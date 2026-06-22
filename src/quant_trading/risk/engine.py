from quant_trading.core.enums import RiskDecisionType, StrategyStatus
from quant_trading.core.models import Bar, OrderIntent, Portfolio, RiskDecision
from quant_trading.risk.rules import RiskRule


class RiskEngine:
    def __init__(self, rules: list[RiskRule]):
        self.rules = rules

    def check_order(
        self,
        intent: OrderIntent,
        latest_bar: Bar | None,
        portfolio: Portfolio,
        strategy_status: StrategyStatus,
    ) -> RiskDecision:
        for rule in self.rules:
            decision = rule.evaluate(intent, latest_bar, portfolio, strategy_status)
            if decision.decision is not RiskDecisionType.APPROVED:
                return decision
        return RiskDecision(RiskDecisionType.APPROVED, "RiskEngine", "all risk rules approved", intent)
