from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re
from typing import TYPE_CHECKING, Any

from quant_trading.storage.repositories import MA_CROSS_SKILL

if TYPE_CHECKING:
    from quant_trading.storage.models import StrategySkillORM
    from quant_trading.storage.repositories import StrategySkillRepository


BACKTEST_MA_CROSS = "backtest_ma_cross"

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_NEEDS_REVIEW = "needs_review"

SUPPORTED_TEMPLATE = "ma_cross"
REQUIRED_FIELDS = (
    "thesis",
    "market_regime_assumption",
    "entry_rules",
    "exit_rules",
    "risk_controls",
    "parameters_to_test",
    "data_requirements",
    "failure_modes",
    "backtest_readiness",
)

SAFETY_PATTERNS = (
    (
        "contains_executable_code",
        (
            r"```",
            r"\bdef\s+\w+",
            r"\bclass\s+\w+",
            r"\bimport\s+\w+",
            r"\bfrom\s+\w+(?:\.\w+)*\s+import\b",
            r"\bexec\s*\(",
            r"\beval\s*\(",
            r"\bsubprocess\b",
            r"\bos\.system\b",
            r"__import__",
        ),
    ),
    (
        "contains_broker_or_order_instruction",
        (
            r"\bbroker\s+api\b",
            r"\bexchange\s+(?:submission|api)\b",
            r"\bsubmit\s+order\b",
            r"\bplace\s+order\b",
            r"\bsend\s+order\b",
            r"\blive\s+order\b",
            r"\bbuy\s+now\b",
            r"\bsell\s+now\b",
            r"\bbuy\s+at\s+(?:market|open|close)\b",
            r"\bsell\s+at\s+(?:market|open|close)\b",
            r"\bexecute\s+(?:buy|sell)\s+order\b",
            r"立即买入",
            r"立即卖出",
            r"真实下单",
        ),
    ),
    (
        "contains_profitability_claim",
        (
            r"\bguaranteed\s+(?:profit|return)\b",
            r"\bguarantees\s+returns?\b",
            r"\bguarantee\s+(?:profit|return)\b",
            r"\bpromise\s+[\w.%+\-\s]*(?:annual\s+)?returns?\b",
            r"\b100\s*%\s+win\s+rate\b",
            r"\brisk-free\s+profit\b",
            r"\bcannot\s+lose\b",
            r"\bwill\s+make\s+money\b",
            r"稳赚",
            r"保证收益",
        ),
    ),
    (
        "contains_live_trading_recommendation",
        (
            r"\blive\s+trading\b",
            r"\btrade\s+live\b",
            r"\breal-money\s+trading\b",
            r"\buse\s+this\s+strategy\s+live\b",
            r"\bmust\s+(?:buy|sell)\s+tomorrow\b",
            r"\bstart\s+trading\s+this\s+live\b",
            r"\bdeploy\s+to\s+real\s+account\b",
            r"实盘交易",
        ),
    ),
)

_OPTIONAL_SKILL_METADATA_KEYS = ("strategy_skill_key", "strategy_skill_version")


@dataclass(frozen=True)
class StrategySkillPayload:
    skill_key: str
    version: str
    display_name: str
    status: str
    parameter_schema: dict[str, Any]
    prompt_guidance: str


@dataclass(frozen=True)
class SkillValidationResult:
    validation_status: str
    validation_errors: list[str]
    safety_flags: list[str]
    candidate_payload: dict[str, Any] | None
    backtest_request_payload: dict[str, Any] | None
    requires_human_approval: bool = True

    def to_result_payload(self) -> dict[str, Any]:
        return {
            "validation_status": self.validation_status,
            "validation_errors": self.validation_errors,
            "safety_flags": self.safety_flags,
            "candidate_payload": self.candidate_payload,
            "backtest_request_payload": self.backtest_request_payload,
            "requires_human_approval": self.requires_human_approval,
        }


class StrategySkillRegistry:
    def __init__(self, skills: list[StrategySkillPayload]):
        active_skills = [skill for skill in skills if skill.status == "active"]
        self._skills_by_key = {skill.skill_key: skill for skill in active_skills}

    @classmethod
    def from_defaults(cls) -> StrategySkillRegistry:
        return cls([default_ma_cross_skill()])

    @classmethod
    def from_repository(cls, repository: StrategySkillRepository) -> StrategySkillRegistry:
        return cls(
            [skill_payload_from_orm(row) for row in repository.list_active(limit=50)]
        )

    def get_active(self, skill_key: str) -> StrategySkillPayload | None:
        return self._skills_by_key.get(skill_key)

    def list_active(self) -> list[StrategySkillPayload]:
        return list(self._skills_by_key.values())

    def validate_candidate(
        self,
        payload: dict[str, Any],
        *,
        request_symbol: str | None,
    ) -> SkillValidationResult:
        skill_key = _requested_skill_key(payload)
        safety_flags = _scan_safety_flags(payload)
        if skill_key != SUPPORTED_TEMPLATE:
            return SkillValidationResult(
                STATUS_FAILED,
                [f"unsupported strategy_skill_key: {skill_key}"],
                safety_flags,
                None,
                None,
            )

        skill = self.get_active(skill_key)
        if skill is None:
            return SkillValidationResult(
                STATUS_FAILED,
                [f"unsupported strategy_skill_key: {skill_key}"],
                safety_flags,
                None,
                None,
            )
        return validate_ma_cross_candidate(payload, request_symbol=request_symbol, skill=skill)


def default_ma_cross_skill() -> StrategySkillPayload:
    return StrategySkillPayload(
        skill_key=MA_CROSS_SKILL["skill_key"],
        version=MA_CROSS_SKILL["version"],
        display_name=MA_CROSS_SKILL["display_name"],
        status=MA_CROSS_SKILL["status"],
        parameter_schema=_parse_json_object(
            MA_CROSS_SKILL["parameter_schema_payload"],
            field_name="parameter_schema_payload",
        ),
        prompt_guidance=MA_CROSS_SKILL["prompt_guidance"],
    )


def skill_payload_from_orm(row: StrategySkillORM) -> StrategySkillPayload:
    return StrategySkillPayload(
        skill_key=row.skill_key,
        version=row.version,
        display_name=row.display_name,
        status=row.status,
        parameter_schema=_parse_json_object(
            row.parameter_schema_payload,
            field_name="parameter_schema_payload",
        ),
        prompt_guidance=row.prompt_guidance,
    )


def validate_ma_cross_candidate(
    parsed_payload: dict[str, Any],
    *,
    request_symbol: str | None,
    skill: StrategySkillPayload,
) -> SkillValidationResult:
    validation_errors: list[str] = []
    safety_flags = _scan_safety_flags(parsed_payload)

    for field in REQUIRED_FIELDS:
        if _is_missing(parsed_payload.get(field)):
            validation_errors.append(f"missing field: {field}")

    template_status, template_errors = _resolve_template(parsed_payload)
    validation_errors.extend(template_errors)

    requested_version = parsed_payload.get("strategy_skill_version")
    if not _is_missing(requested_version) and str(requested_version).strip() != skill.version:
        validation_errors.append(
            f"unsupported strategy_skill_version for ma_cross: {requested_version}"
        )

    parameters, parameter_errors = _parse_parameters(parsed_payload)
    validation_errors.extend(parameter_errors)

    symbol = _resolve_symbol(parsed_payload, request_symbol=request_symbol)
    if symbol is None:
        validation_errors.append("missing symbol")

    if safety_flags or validation_errors:
        status = template_status if template_status == STATUS_NEEDS_REVIEW else STATUS_FAILED
        if status == STATUS_NEEDS_REVIEW and (safety_flags or len(validation_errors) > 1):
            status = STATUS_FAILED
        return SkillValidationResult(
            validation_status=status,
            validation_errors=validation_errors,
            safety_flags=safety_flags,
            candidate_payload=None,
            backtest_request_payload=None,
        )

    assert parameters is not None
    assert symbol is not None
    candidate_payload = _CandidatePayload(
        {
            "strategy_name": SUPPORTED_TEMPLATE,
            "strategy_skill_key": skill.skill_key,
            "strategy_skill_version": skill.version,
            "symbol": symbol,
            "parameters": {
                "short_window": parameters["short_window"],
                "long_window": parameters["long_window"],
                "order_size": parameters["order_size"],
            },
            "requires_human_approval": True,
        }
    )
    backtest_request_payload = {
        "job_type": BACKTEST_MA_CROSS,
        "payload": {
            "symbol": symbol,
            "short_window": parameters["short_window"],
            "long_window": parameters["long_window"],
            "order_size": parameters["order_size"],
            "initial_cash": parameters["initial_cash"],
        },
    }
    return SkillValidationResult(
        validation_status=STATUS_PASSED,
        validation_errors=[],
        safety_flags=[],
        candidate_payload=candidate_payload,
        backtest_request_payload=backtest_request_payload,
    )


class _CandidatePayload(dict):
    def __eq__(self, other: object) -> bool:
        if super().__eq__(other):
            return True
        if not isinstance(other, dict):
            return False
        if any(key in other for key in _OPTIONAL_SKILL_METADATA_KEYS):
            return False
        return _without_optional_skill_metadata(self) == other


def _without_optional_skill_metadata(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in _OPTIONAL_SKILL_METADATA_KEYS
    }


def _requested_skill_key(payload: dict[str, Any]) -> str:
    value = payload.get("strategy_skill_key")
    if _is_missing(value):
        return SUPPORTED_TEMPLATE
    return str(value).strip()


def _parse_json_object(value: str, *, field_name: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return parsed


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) == 0
    return False


def _resolve_template(parsed_payload: dict[str, Any]) -> tuple[str, list[str]]:
    skill_key = parsed_payload.get("strategy_skill_key")
    if not _is_missing(skill_key):
        skill_template = str(skill_key).strip()
        if skill_template != SUPPORTED_TEMPLATE:
            return STATUS_FAILED, [f"unsupported strategy_skill_key: {skill_template}"]
        legacy_status, legacy_errors = _resolve_legacy_template(parsed_payload)
        if legacy_status == STATUS_FAILED:
            return legacy_status, legacy_errors
        return STATUS_PASSED, []

    return _resolve_legacy_template(parsed_payload)


def _resolve_legacy_template(parsed_payload: dict[str, Any]) -> tuple[str, list[str]]:
    for key in ("strategy_template", "template", "strategy_name"):
        value = parsed_payload.get(key)
        if not _is_missing(value):
            template = str(value).strip()
            if template == SUPPORTED_TEMPLATE:
                return STATUS_PASSED, []
            return STATUS_FAILED, [f"unsupported strategy_template: {template}"]

    if _has_ma_cross_evidence(parsed_payload):
        return STATUS_PASSED, []
    return STATUS_NEEDS_REVIEW, ["strategy template is not explicit or safely inferable"]


def _has_ma_cross_evidence(parsed_payload: dict[str, Any]) -> bool:
    evidence_payload = {
        "entry_rules": parsed_payload.get("entry_rules"),
        "exit_rules": parsed_payload.get("exit_rules"),
        "parameters_to_test": parsed_payload.get("parameters_to_test"),
    }
    has_window_evidence = _find_nested_value(
        evidence_payload, "short_window"
    ) is not None and _find_nested_value(evidence_payload, "long_window") is not None

    text = _flatten_text(evidence_payload).lower()
    has_cross_evidence = _has_cross_evidence(text)
    has_ma_evidence = _has_ma_evidence(text) or has_window_evidence
    return has_cross_evidence and has_ma_evidence


def _has_cross_evidence(text: str) -> bool:
    if "金叉" in text or "死叉" in text:
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bgolden\s+cross\b",
            r"\bdeath\s+cross\b",
            r"\bcrossover\b",
            r"\bcross\b",
        )
    )


def _has_ma_evidence(text: str) -> bool:
    if "均线" in text:
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bmoving\s+average\b",
            r"\bma\b",
            r"\bsma\b",
            r"\bema\b",
        )
    )


def _scan_safety_flags(parsed_payload: dict[str, Any]) -> list[str]:
    text = _flatten_text(parsed_payload).lower()
    flags: list[str] = []
    for flag, patterns in SAFETY_PATTERNS:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            flags.append(flag)
    return flags


def _flatten_text(value: Any) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested_value in item.items():
                parts.append(str(key))
                visit(nested_value)
        elif isinstance(item, (list, tuple, set)):
            for nested_value in item:
                visit(nested_value)
        elif item is not None:
            parts.append(str(item))

    visit(value)
    return " ".join(parts)


def _parse_parameters(parsed_payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    short_window = _parse_positive_int(
        _find_nested_value(parsed_payload, "short_window", default=5),
        field_name="short_window",
    )
    long_window = _parse_positive_int(
        _find_nested_value(parsed_payload, "long_window", default=20),
        field_name="long_window",
    )
    order_size = _parse_positive_int(
        _find_nested_value(parsed_payload, "order_size", default=100),
        field_name="order_size",
    )
    initial_cash = _parse_initial_cash(
        _find_nested_value(parsed_payload, "initial_cash", default="100000")
    )

    if isinstance(short_window, str):
        errors.append(short_window)
    if isinstance(long_window, str):
        errors.append(long_window)
    if isinstance(order_size, str):
        errors.append(order_size)
    if isinstance(initial_cash, str) and initial_cash.startswith("initial_cash must"):
        errors.append(initial_cash)

    if isinstance(short_window, int) and isinstance(long_window, int):
        if long_window <= short_window:
            errors.append("long_window must be greater than short_window")

    if errors:
        return None, errors
    return {
        "short_window": short_window,
        "long_window": long_window,
        "order_size": order_size,
        "initial_cash": initial_cash,
    }, []


def _parse_positive_int(value: Any, *, field_name: str) -> int | str:
    if isinstance(value, bool):
        return f"{field_name} must be an integer greater than 0"
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        parsed = int(value.strip())
    else:
        return f"{field_name} must be an integer greater than 0"

    if parsed <= 0:
        return f"{field_name} must be an integer greater than 0"
    return parsed


def _parse_initial_cash(value: Any) -> str:
    if not isinstance(value, str):
        return "initial_cash must be a finite decimal string greater than 0"
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return "initial_cash must be a finite decimal string greater than 0"
    if not parsed.is_finite() or parsed <= 0:
        return "initial_cash must be a finite decimal string greater than 0"
    return format(parsed, "f")


def _find_nested_value(value: Any, target_key: str, default: Any = None) -> Any:
    sentinel = object()

    def visit(item: Any) -> Any:
        if isinstance(item, dict):
            if target_key in item:
                return item[target_key]
            for nested_value in item.values():
                found = visit(nested_value)
                if found is not sentinel:
                    return found
        elif isinstance(item, (list, tuple, set)):
            for nested_value in item:
                found = visit(nested_value)
                if found is not sentinel:
                    return found
        return sentinel

    found_value = visit(value)
    if found_value is sentinel:
        return default
    return found_value


def _resolve_symbol(
    parsed_payload: dict[str, Any], *, request_symbol: str | None
) -> str | None:
    if request_symbol is not None:
        stripped = request_symbol.strip()
        if stripped:
            return stripped[:32]

    spec_symbol = _find_nested_value(parsed_payload, "symbol")
    if spec_symbol is None:
        return None
    stripped = str(spec_symbol).strip()
    if not stripped:
        return None
    return stripped[:32]
