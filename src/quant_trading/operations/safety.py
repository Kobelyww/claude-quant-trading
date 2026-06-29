from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from quant_trading.core.enums import OrderSide, OrderType
from quant_trading.core.models import Bar
from quant_trading.storage.models import (
    ExecutionOrderIntentORM,
    ExecutionSafetyStateORM,
    OperatorApprovalRequestORM,
)
from quant_trading.storage.repositories import (
    ExecutionOrderDecisionRepository,
    ExecutionOrderIntentRepository,
    ExecutionSafetyStateRepository,
    OperatorApprovalRequestRepository,
)


def _decimal(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _date_only(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _try_decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    try:
        decimal_value = _decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return decimal_value if decimal_value.is_finite() else None


def _try_int(value: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _try_date_only(value: date | datetime | str) -> date | None:
    try:
        return _date_only(value)
    except (TypeError, ValueError):
        return None


_VALID_BROKER_MODES = frozenset({"simulated", "dry_run", "live"})
_VALID_ORDER_SIDES = frozenset(item.value for item in OrderSide)
_VALID_ORDER_TYPES = frozenset(item.value for item in OrderType)


@dataclass(frozen=True)
class PreLiveRiskProfile:
    name: str
    max_single_order_notional: Decimal
    max_gross_exposure_ratio: Decimal
    max_daily_turnover: Decimal
    max_daily_order_count: int
    max_drawdown_stop_ratio: Decimal
    stale_data_max_age_days: int
    manual_approval_notional: Decimal
    manual_approval_sell_without_position: bool
    allowed_broker_modes: set[str]

    @classmethod
    def default(cls) -> PreLiveRiskProfile:
        return cls(
            name="pre_live_default",
            max_single_order_notional=Decimal("100000"),
            max_gross_exposure_ratio=Decimal("1.0"),
            max_daily_turnover=Decimal("300000"),
            max_daily_order_count=20,
            max_drawdown_stop_ratio=Decimal("0.10"),
            stale_data_max_age_days=10,
            manual_approval_notional=Decimal("50000"),
            manual_approval_sell_without_position=True,
            allowed_broker_modes={"simulated", "dry_run"},
        )


@dataclass(frozen=True)
class SafetyPolicyInput:
    client_order_id: str
    symbol: str
    instrument_id: int
    side: OrderSide | str
    order_type: OrderType | str
    quantity: int
    limit_price: Decimal | None
    estimated_price: Decimal | None
    broker_mode: str
    latest_bar: Bar | None
    as_of: date | datetime
    cash: Decimal = Decimal("0")
    market_value: Decimal = Decimal("0")
    peak_equity: Decimal | None = None
    daily_turnover: Decimal = Decimal("0")
    daily_order_count: int = 0
    position_quantity: int = 0
    source_type: str = "manual_test"
    source_id: int | None = None
    paper_run_id: int | None = None
    paper_order_id: int | None = None
    kill_switch_active: bool = False
    dry_run_enabled: bool = True
    simulated_enabled: bool = True
    live_enabled: bool = False

    @property
    def side_value(self) -> str:
        return _enum_value(self.side)

    @property
    def order_type_value(self) -> str:
        return _enum_value(self.order_type)

    @property
    def as_of_date(self) -> date:
        return _date_only(self.as_of)

    @property
    def order_notional(self) -> Decimal:
        return _decimal(self.estimated_price) * Decimal(self.quantity)


@dataclass(frozen=True)
class PreLiveSafetyDecision:
    decision_type: str
    reason_code: str
    message: str
    broker_submission_allowed: bool
    order_status: str | None = None
    order_intent_id: int | None = None
    approval_request_id: int | None = None


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    reason_code: str
    message: str
    broker_submission_allowed: bool


class ExecutionOrderStateMachine:
    _ALLOWED_TRANSITIONS = {
        "created": frozenset(
            {"risk_approved", "approval_required", "blocked", "cancelled"}
        ),
        "approval_required": frozenset({"operator_approved", "blocked", "cancelled"}),
        "risk_approved": frozenset({"submitted", "skipped", "cancelled"}),
        "operator_approved": frozenset({"submitted", "skipped"}),
    }

    @classmethod
    def validate(cls, current_status: str, next_status: str) -> None:
        if next_status not in cls._ALLOWED_TRANSITIONS.get(current_status, frozenset()):
            raise ValueError(
                "invalid execution order transition "
                f"from {current_status} to {next_status}"
            )


class PreLiveSafetyService:
    def __init__(
        self,
        session: Session | None = None,
        profile: PreLiveRiskProfile | None = None,
    ):
        self.session = session
        self.profile = profile or PreLiveRiskProfile.default()

    def evaluate_policy(self, policy_input: SafetyPolicyInput) -> PreLiveSafetyDecision:
        self._validate_broker_mode(policy_input.broker_mode)
        decision = self._evaluate_policy(policy_input)
        return PreLiveSafetyDecision(
            decision_type=decision.decision,
            reason_code=decision.reason_code,
            message=decision.message,
            broker_submission_allowed=decision.broker_submission_allowed,
        )

    def evaluate_order_intent(
        self,
        policy_input: SafetyPolicyInput,
        *,
        now: datetime | None = None,
    ) -> PreLiveSafetyDecision:
        session = self._require_session()
        now = now or datetime.utcnow()
        intent_repo = ExecutionOrderIntentRepository(session)
        self._validate_broker_mode(policy_input.broker_mode)
        safety_state = ExecutionSafetyStateRepository(session).get_or_create_global(now)
        merged_input = self._with_safety_state(policy_input, safety_state)
        policy_decision = self._evaluate_policy(merged_input)
        estimated_price = self._safe_estimated_price(merged_input)
        estimated_notional = self._safe_order_notional(merged_input)
        intent, created = intent_repo.get_or_create(
            source_type=merged_input.source_type,
            source_id=merged_input.source_id,
            paper_run_id=merged_input.paper_run_id,
            paper_order_id=merged_input.paper_order_id,
            client_order_id=merged_input.client_order_id,
            symbol=merged_input.symbol,
            instrument_id=merged_input.instrument_id,
            side=merged_input.side_value,
            order_type=merged_input.order_type_value,
            quantity=self._safe_order_quantity(merged_input),
            limit_price=self._safe_limit_price(merged_input),
            estimated_price=estimated_price,
            estimated_notional=estimated_notional,
            broker_mode=merged_input.broker_mode,
            risk_profile_name=self.profile.name,
            risk_summary_payload=self._order_intent_payload(
                merged_input,
                estimated_notional=estimated_notional,
            ),
            approval_required=policy_decision.decision == "approval_required",
            created_at=now,
            updated_at=now,
        )
        if not created and intent.status != "created":
            return self._skipped_existing_intent(intent)

        if policy_decision.decision == "approved":
            return self._persist_policy_result(
                intent=intent,
                order_status="risk_approved",
                policy_decision=policy_decision,
                policy_input=merged_input,
                now=now,
            )
        if policy_decision.decision == "blocked":
            return self._persist_policy_result(
                intent=intent,
                order_status="blocked",
                policy_decision=policy_decision,
                policy_input=merged_input,
                now=now,
            )
        approval = OperatorApprovalRequestRepository(session).create_pending(
            resource_type="execution_order_intent",
            resource_id=intent.id,
            reason_code=policy_decision.reason_code,
            requested_by="system",
            requested_at=now,
            expires_at=None,
        )
        return self._persist_policy_result(
            intent=intent,
            order_status="approval_required",
            policy_decision=policy_decision,
            policy_input=merged_input,
            now=now,
            approval_request=approval,
        )

    def approve_order_intent(
        self,
        order_intent_id: int,
        *,
        operator: str,
        note: str = "",
        now: datetime | None = None,
    ) -> PreLiveSafetyDecision:
        session = self._require_session()
        now = now or datetime.utcnow()
        operator, note = self._validate_operator_decision(operator, note)
        approval_repo = OperatorApprovalRequestRepository(session)
        intent = self._get_order_intent(order_intent_id)
        approval = self._get_intent_approval(approval_repo, intent)
        ExecutionOrderStateMachine.validate(intent.status, "operator_approved")
        approval_repo.decide(
            approval,
            status="approved",
            operator=operator,
            note=note,
            decided_at=now,
        )
        policy_decision = PolicyDecision(
            decision="approved",
            reason_code="approved",
            message="operator approved order intent",
            broker_submission_allowed=True,
        )
        ExecutionOrderIntentRepository(session).set_status(
            intent,
            "operator_approved",
            now,
            approval_required=False,
        )
        self._record_decision(intent, policy_decision, {}, now)
        return PreLiveSafetyDecision(
            decision_type=policy_decision.decision,
            reason_code=policy_decision.reason_code,
            message=policy_decision.message,
            broker_submission_allowed=policy_decision.broker_submission_allowed,
            order_status=intent.status,
            order_intent_id=intent.id,
            approval_request_id=approval.id,
        )

    def reject_order_intent(
        self,
        order_intent_id: int,
        *,
        operator: str,
        note: str = "",
        now: datetime | None = None,
    ) -> PreLiveSafetyDecision:
        session = self._require_session()
        now = now or datetime.utcnow()
        operator, note = self._validate_operator_decision(operator, note)
        approval_repo = OperatorApprovalRequestRepository(session)
        intent = self._get_order_intent(order_intent_id)
        approval = self._get_intent_approval(approval_repo, intent)
        ExecutionOrderStateMachine.validate(intent.status, "blocked")
        approval_repo.decide(
            approval,
            status="rejected",
            operator=operator,
            note=note,
            decided_at=now,
        )
        policy_decision = PolicyDecision(
            decision="blocked",
            reason_code="blocked_operator_rejected",
            message="operator rejected order intent",
            broker_submission_allowed=False,
        )
        ExecutionOrderIntentRepository(session).set_status(
            intent,
            "blocked",
            now,
            approval_required=False,
            blocked_reason_code=policy_decision.reason_code,
            blocked_reason=policy_decision.message,
        )
        self._record_decision(intent, policy_decision, {}, now)
        return PreLiveSafetyDecision(
            decision_type=policy_decision.decision,
            reason_code=policy_decision.reason_code,
            message=policy_decision.message,
            broker_submission_allowed=policy_decision.broker_submission_allowed,
            order_status=intent.status,
            order_intent_id=intent.id,
            approval_request_id=approval.id,
        )

    def _evaluate_policy(self, policy_input: SafetyPolicyInput) -> PolicyDecision:
        self._validate_broker_mode(policy_input.broker_mode)
        if policy_input.broker_mode == "live":
            return self._blocked(
                "blocked_live_mode_unavailable",
                "live broker mode is unavailable for pre-live safety",
            )
        if not self._is_valid_order_intent(policy_input):
            return self._blocked(
                "blocked_invalid_order_intent",
                "order intent is malformed",
            )
        if policy_input.kill_switch_active:
            return self._blocked(
                "blocked_global_kill_switch",
                "global execution kill switch is active",
            )
        if not self._broker_mode_enabled(policy_input):
            return self._blocked(
                "blocked_broker_mode_disabled",
                "broker mode is not enabled by execution safety state",
            )
        if self._is_stale_market_data(policy_input):
            return self._blocked(
                "blocked_stale_market_data",
                "latest market data is missing or stale",
            )
        if not self._has_valid_price(policy_input):
            return self._blocked("blocked_invalid_price", "latest price is invalid")
        notional = policy_input.order_notional
        if notional > self.profile.max_single_order_notional:
            return self._blocked(
                "blocked_max_single_order_notional",
                "single order notional exceeds policy maximum",
            )
        daily_turnover = _try_decimal(policy_input.daily_turnover)
        if (
            daily_turnover is None
            or daily_turnover + notional > self.profile.max_daily_turnover
        ):
            return self._blocked(
                "blocked_max_daily_turnover",
                "daily turnover exceeds policy maximum",
            )
        daily_order_count = _try_int(policy_input.daily_order_count)
        if (
            daily_order_count is None
            or daily_order_count >= self.profile.max_daily_order_count
        ):
            return self._blocked(
                "blocked_max_daily_order_count",
                "daily order count reached policy maximum",
            )
        if (
            not self._has_valid_portfolio_scalars(policy_input)
            or self._equity(policy_input) <= 0
        ):
            return self._blocked(
                "blocked_max_gross_exposure",
                "gross exposure exceeds policy maximum",
            )
        if self._exposure_ratio(policy_input) > self.profile.max_gross_exposure_ratio:
            return self._blocked(
                "blocked_max_gross_exposure",
                "gross exposure exceeds policy maximum",
            )
        if self._drawdown(policy_input) > self.profile.max_drawdown_stop_ratio:
            return self._blocked(
                "blocked_drawdown_stop",
                "portfolio drawdown exceeds pre-live stop threshold",
            )
        if (
            self.profile.manual_approval_sell_without_position
            and policy_input.side_value == "sell"
            and self._safe_position_quantity(policy_input)
            < self._safe_order_quantity(policy_input)
        ):
            return self._approval_required(
                "manual_approval_required_sell_without_position",
                "sell order exceeds current position and requires operator approval",
            )
        if notional > self.profile.manual_approval_notional:
            return self._approval_required(
                "manual_approval_required_notional",
                "order notional exceeds manual approval threshold",
            )
        return PolicyDecision(
            decision="approved",
            reason_code="approved",
            message="order intent approved by pre-live safety policy",
            broker_submission_allowed=True,
        )

    def _persist_policy_result(
        self,
        *,
        intent: ExecutionOrderIntentORM,
        order_status: str,
        policy_decision: PolicyDecision,
        policy_input: SafetyPolicyInput,
        now: datetime,
        approval_request: OperatorApprovalRequestORM | None = None,
    ) -> PreLiveSafetyDecision:
        session = self._require_session()
        ExecutionOrderStateMachine.validate(intent.status, order_status)
        ExecutionOrderIntentRepository(session).set_status(
            intent,
            order_status,
            now,
            approval_required=policy_decision.decision == "approval_required",
            approval_request_id=approval_request.id if approval_request else None,
            blocked_reason_code=(
                policy_decision.reason_code
                if policy_decision.decision == "blocked"
                else None
            ),
            blocked_reason=(
                policy_decision.message if policy_decision.decision == "blocked" else None
            ),
        )
        self._record_decision(
            intent,
            policy_decision,
            self._policy_payload(
                policy_input,
                policy_decision,
                estimated_notional=self._safe_order_notional(policy_input),
            ),
            now,
        )
        return PreLiveSafetyDecision(
            decision_type=policy_decision.decision,
            reason_code=policy_decision.reason_code,
            message=policy_decision.message,
            broker_submission_allowed=policy_decision.broker_submission_allowed,
            order_status=intent.status,
            order_intent_id=intent.id,
            approval_request_id=approval_request.id if approval_request else None,
        )

    def _record_decision(
        self,
        intent: ExecutionOrderIntentORM,
        policy_decision: PolicyDecision,
        policy_payload: dict,
        now: datetime,
    ) -> None:
        ExecutionOrderDecisionRepository(self._require_session()).record(
            order_intent_id=intent.id,
            decision_type=policy_decision.decision,
            reason_code=policy_decision.reason_code,
            message=policy_decision.message,
            policy_payload=policy_payload,
            created_at=now,
        )

    def _skipped_existing_intent(
        self,
        intent: ExecutionOrderIntentORM,
    ) -> PreLiveSafetyDecision:
        return PreLiveSafetyDecision(
            decision_type="skipped",
            reason_code="skipped_duplicate_client_order_id",
            message="order intent was already evaluated",
            broker_submission_allowed=False,
            order_status=intent.status,
            order_intent_id=intent.id,
            approval_request_id=intent.approval_request_id,
        )

    def _policy_payload(
        self,
        policy_input: SafetyPolicyInput,
        policy_decision: PolicyDecision,
        *,
        estimated_notional: Decimal | None = None,
    ) -> dict:
        estimated_notional = (
            self._safe_order_notional(policy_input)
            if estimated_notional is None
            else estimated_notional
        )
        return {
            "profile_name": self.profile.name,
            "client_order_id": policy_input.client_order_id,
            "symbol": policy_input.symbol,
            "instrument_id": policy_input.instrument_id,
            "side": policy_input.side_value,
            "order_type": policy_input.order_type_value,
            "quantity": policy_input.quantity,
            "estimated_price": policy_input.estimated_price,
            "estimated_notional": estimated_notional,
            "broker_mode": policy_input.broker_mode,
            "latest_bar_timestamp": (
                policy_input.latest_bar.timestamp if policy_input.latest_bar else None
            ),
            "as_of": policy_input.as_of,
            "cash": policy_input.cash,
            "market_value": policy_input.market_value,
            "peak_equity": policy_input.peak_equity,
            "daily_turnover": policy_input.daily_turnover,
            "daily_order_count": policy_input.daily_order_count,
            "position_quantity": policy_input.position_quantity,
            "kill_switch_active": policy_input.kill_switch_active,
            "dry_run_enabled": policy_input.dry_run_enabled,
            "simulated_enabled": policy_input.simulated_enabled,
            "live_enabled": policy_input.live_enabled,
            "decision": policy_decision.decision,
            "reason_code": policy_decision.reason_code,
            "broker_submission_allowed": policy_decision.broker_submission_allowed,
        }

    def _order_intent_payload(
        self,
        policy_input: SafetyPolicyInput,
        *,
        estimated_notional: Decimal | None = None,
    ) -> dict:
        estimated_notional = (
            self._safe_order_notional(policy_input)
            if estimated_notional is None
            else estimated_notional
        )
        return {
            "profile_name": self.profile.name,
            "client_order_id": policy_input.client_order_id,
            "symbol": policy_input.symbol,
            "instrument_id": policy_input.instrument_id,
            "side": policy_input.side_value,
            "order_type": policy_input.order_type_value,
            "quantity": policy_input.quantity,
            "estimated_price": policy_input.estimated_price,
            "estimated_notional": estimated_notional,
            "broker_mode": policy_input.broker_mode,
            "latest_bar_timestamp": (
                policy_input.latest_bar.timestamp if policy_input.latest_bar else None
            ),
            "as_of": policy_input.as_of,
            "cash": policy_input.cash,
            "market_value": policy_input.market_value,
            "peak_equity": policy_input.peak_equity,
            "daily_turnover": policy_input.daily_turnover,
            "daily_order_count": policy_input.daily_order_count,
            "position_quantity": policy_input.position_quantity,
        }

    def _with_safety_state(
        self,
        policy_input: SafetyPolicyInput,
        safety_state: ExecutionSafetyStateORM,
    ) -> SafetyPolicyInput:
        return SafetyPolicyInput(
            client_order_id=policy_input.client_order_id,
            symbol=policy_input.symbol,
            instrument_id=policy_input.instrument_id,
            side=policy_input.side,
            order_type=policy_input.order_type,
            quantity=policy_input.quantity,
            limit_price=policy_input.limit_price,
            estimated_price=policy_input.estimated_price,
            broker_mode=policy_input.broker_mode,
            latest_bar=policy_input.latest_bar,
            as_of=policy_input.as_of,
            cash=policy_input.cash,
            market_value=policy_input.market_value,
            peak_equity=policy_input.peak_equity,
            daily_turnover=policy_input.daily_turnover,
            daily_order_count=policy_input.daily_order_count,
            position_quantity=policy_input.position_quantity,
            source_type=policy_input.source_type,
            source_id=policy_input.source_id,
            paper_run_id=policy_input.paper_run_id,
            paper_order_id=policy_input.paper_order_id,
            kill_switch_active=safety_state.kill_switch_active,
            dry_run_enabled=safety_state.dry_run_enabled,
            simulated_enabled=safety_state.simulated_enabled,
            live_enabled=safety_state.live_enabled,
        )

    def _broker_mode_enabled(self, policy_input: SafetyPolicyInput) -> bool:
        self._validate_broker_mode(policy_input.broker_mode)
        if policy_input.broker_mode not in self.profile.allowed_broker_modes:
            return False
        if policy_input.broker_mode == "simulated":
            return policy_input.simulated_enabled
        if policy_input.broker_mode == "dry_run":
            return policy_input.dry_run_enabled
        return False

    def _is_stale_market_data(self, policy_input: SafetyPolicyInput) -> bool:
        if policy_input.latest_bar is None:
            return True
        latest_date = _try_date_only(policy_input.latest_bar.timestamp)
        as_of_date = _try_date_only(policy_input.as_of)
        if latest_date is None or as_of_date is None:
            return True
        return (as_of_date - latest_date).days > self.profile.stale_data_max_age_days

    def _drawdown(self, policy_input: SafetyPolicyInput) -> Decimal:
        equity = self._equity(policy_input)
        peak_equity = (
            _try_decimal(policy_input.peak_equity)
            if policy_input.peak_equity is not None
            else equity
        )
        if peak_equity is None:
            return Decimal("Infinity")
        if peak_equity <= 0:
            return Decimal("0")
        return (peak_equity - equity) / peak_equity

    def _exposure_ratio(self, policy_input: SafetyPolicyInput) -> Decimal:
        equity = self._equity(policy_input)
        if equity <= 0:
            return Decimal("Infinity")
        return abs(self._post_order_market_value(policy_input)) / equity

    def _post_order_market_value(self, policy_input: SafetyPolicyInput) -> Decimal:
        market_value = _try_decimal(policy_input.market_value) or Decimal("0")
        notional = self._safe_order_notional(policy_input)
        if policy_input.side_value == "buy":
            return market_value + notional
        if policy_input.side_value == "sell":
            existing_position_value = (
                self._safe_estimated_price(policy_input)
                * Decimal(max(self._safe_position_quantity(policy_input), 0))
            )
            reduction = min(notional, existing_position_value)
            uncovered_notional = max(notional - existing_position_value, Decimal("0"))
            return market_value - reduction + uncovered_notional
        return market_value

    def _is_valid_order_intent(self, policy_input: SafetyPolicyInput) -> bool:
        quantity = _try_int(policy_input.quantity)
        if quantity is None:
            return False
        if policy_input.limit_price is not None:
            limit_price = _try_decimal(policy_input.limit_price)
            if limit_price is None or limit_price <= 0:
                return False
        return quantity > 0 and policy_input.side_value in _VALID_ORDER_SIDES and (
            policy_input.order_type_value in _VALID_ORDER_TYPES
        )

    def _has_valid_portfolio_scalars(self, policy_input: SafetyPolicyInput) -> bool:
        if _try_decimal(policy_input.cash) is None:
            return False
        if _try_decimal(policy_input.market_value) is None:
            return False
        if policy_input.peak_equity is not None and (
            _try_decimal(policy_input.peak_equity) is None
        ):
            return False
        return _try_int(policy_input.position_quantity) is not None

    def _has_valid_price(self, policy_input: SafetyPolicyInput) -> bool:
        estimated_price = _try_decimal(policy_input.estimated_price)
        if estimated_price is None or estimated_price <= 0:
            return False
        if policy_input.latest_bar is None:
            return False
        latest_close = _try_decimal(policy_input.latest_bar.close)
        return latest_close is not None and latest_close > 0

    def _safe_order_notional(self, policy_input: SafetyPolicyInput) -> Decimal:
        estimated_price = self._safe_estimated_price(policy_input)
        if estimated_price <= 0:
            return Decimal("0")
        quantity = self._safe_order_quantity(policy_input)
        if quantity <= 0:
            return Decimal("0")
        return estimated_price * Decimal(quantity)

    def _safe_estimated_price(self, policy_input: SafetyPolicyInput) -> Decimal:
        return _try_decimal(policy_input.estimated_price) or Decimal("0")

    def _safe_limit_price(self, policy_input: SafetyPolicyInput) -> Decimal | None:
        if policy_input.limit_price is None:
            return None
        limit_price = _try_decimal(policy_input.limit_price)
        return limit_price if limit_price is not None and limit_price > 0 else None

    def _safe_order_quantity(self, policy_input: SafetyPolicyInput) -> int:
        return _try_int(policy_input.quantity) or 0

    def _safe_position_quantity(self, policy_input: SafetyPolicyInput) -> int:
        return _try_int(policy_input.position_quantity) or 0

    def _equity(self, policy_input: SafetyPolicyInput) -> Decimal:
        cash = _try_decimal(policy_input.cash) or Decimal("0")
        market_value = _try_decimal(policy_input.market_value) or Decimal("0")
        return cash + market_value

    def _validate_broker_mode(self, broker_mode: str) -> None:
        if broker_mode not in _VALID_BROKER_MODES:
            raise ValueError(f"invalid broker mode: {broker_mode}")

    def _validate_operator_decision(self, operator: str, note: str) -> tuple[str, str]:
        operator = operator.strip()
        note = note.strip()
        if not operator or not note:
            raise ValueError("operator and note are required")
        return operator, note

    def _get_order_intent(self, order_intent_id: int) -> ExecutionOrderIntentORM:
        intent = ExecutionOrderIntentRepository(self._require_session()).get(
            order_intent_id
        )
        if intent is None:
            raise ValueError(f"execution order intent not found: {order_intent_id}")
        return intent

    def _get_intent_approval(
        self,
        approval_repo: OperatorApprovalRequestRepository,
        intent: ExecutionOrderIntentORM,
    ) -> OperatorApprovalRequestORM:
        if intent.approval_request_id is None:
            raise ValueError("order intent has no approval request")
        approval = approval_repo.get(intent.approval_request_id)
        if approval is None:
            raise ValueError(f"approval request not found: {intent.approval_request_id}")
        if (
            approval.resource_type != "execution_order_intent"
            or approval.resource_id != intent.id
        ):
            raise ValueError("approval request does not match execution order intent")
        return approval

    def _require_session(self) -> Session:
        if self.session is None:
            raise ValueError("session is required for persistence operations")
        return self.session

    def _blocked(self, reason_code: str, message: str) -> PolicyDecision:
        return PolicyDecision(
            decision="blocked",
            reason_code=reason_code,
            message=message,
            broker_submission_allowed=False,
        )

    def _approval_required(self, reason_code: str, message: str) -> PolicyDecision:
        return PolicyDecision(
            decision="approval_required",
            reason_code=reason_code,
            message=message,
            broker_submission_allowed=False,
        )
