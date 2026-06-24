# Quant Agent v2 Candidate Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `strategy_idea` agent output into a validated, research-only `ma_cross` candidate plus an explicit human-approved backtest request suggestion.

**Architecture:** Add a focused `quant_trading.agents.candidates` module that validates parsed LLM strategy specs, scans safety flags, maps only safe `ma_cross` ideas to existing backtest payload shape, and never submits a job. Integrate it into `run_strategy_idea_agent()` after JSON parsing so existing job and agent-run storage paths persist enriched result payloads without schema changes.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, pytest, existing `FakeLLMClient`, existing job runtime constants and storage models.

---

## Branch And Scope Notes

- Working branch: `codex/quant-agent-v2-candidate-validation`.
- This branch is stacked on `codex/quant-agent-v1`; do not merge to `main` until v1 lands or v2 is rebased.
- Design spec: `docs/superpowers/specs/2026-06-24-quant-agent-v2-candidate-validation-design.md`.
- This plan adds candidate validation only. It does not add generated-code execution, strategy approval, paper runs, broker calls, auto backtest submission, dashboard changes, or schema migrations.

## File Structure

- Create: `src/quant_trading/agents/candidates.py`
  - Owns required-field checks, safety scanning, template resolution, parameter parsing, candidate payload construction, and backtest request payload construction.
  - Must not import broker adapters, paper trading services, strategy classes, queue services, or job submission functions.
  - Uses stable job type string `"backtest_ma_cross"` to avoid a runtime import cycle.
- Create: `tests/unit/test_strategy_candidates.py`
  - Direct unit coverage for validator behavior and safety boundaries.
- Modify: `src/quant_trading/agents/service.py`
  - Calls `validate_strategy_candidate()` only when `parse_strategy_idea_response()` returns `parsed=True`.
  - Adds a `needs_review` validation block for unparseable LLM text.
- Modify: `tests/integration/test_agents_jobs.py`
  - Updates strategy idea fake LLM payloads to complete `ma_cross` specs.
  - Verifies candidate persistence through service and job API.
  - Verifies candidate generation creates no `backtest_runs`, `paper_runs`, or `broker_order_events`.
- Modify: `README.md`
  - Rename the `Quant Agent v1` section to `Quant Agent`.
  - Document v2 candidate validation, `ma_cross`-only support, human approval, and explicit operator backtest submission.

## Review Protocol For Every Implementation Task

Each task must finish with these two reviews before commit:

1. **Spec review:** Check the task against `docs/superpowers/specs/2026-06-24-quant-agent-v2-candidate-validation-design.md`. Confirm it implements only the planned behavior and does not add non-goal behavior.
2. **Quality review:** Check naming, boundary conditions, imports, serialization shape, and test coverage. Confirm no secrets, credentials, broker calls, paper-run creation, or automatic backtest submission were introduced.

Record the review result in the task commit message body when useful, or in the implementation notes before committing.

---

### Task 1: Candidate Validator Unit Tests And Implementation

**Files:**
- Create: `tests/unit/test_strategy_candidates.py`
- Create: `src/quant_trading/agents/candidates.py`

- [ ] **Step 1: Write failing validator tests**

Create `tests/unit/test_strategy_candidates.py` with this content:

```python
import pytest

from quant_trading.agents.candidates import validate_strategy_candidate


def complete_ma_cross_spec(**overrides):
    spec = {
        "strategy_template": "ma_cross",
        "symbol": "000001",
        "thesis": "Trend continuation can be researched with a moving-average crossover.",
        "market_regime_assumption": "Works best in directional markets with enough liquidity.",
        "entry_rules": [
            "Enter research long exposure when the short moving average crosses above the long moving average."
        ],
        "exit_rules": [
            "Exit research exposure when the short moving average crosses below the long moving average."
        ],
        "risk_controls": ["Use fixed order size and inspect drawdown before any paper run."],
        "parameters_to_test": {
            "short_window": 8,
            "long_window": 34,
            "order_size": 200,
            "initial_cash": "150000.50",
        },
        "data_requirements": ["Daily OHLCV bars for the selected symbol."],
        "failure_modes": ["Range-bound markets can create repeated false crosses."],
        "backtest_readiness": "ready",
    }
    spec.update(overrides)
    return spec


def test_valid_ma_cross_spec_creates_candidate_and_backtest_request():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(),
        request_symbol="000002",
    )

    assert result == {
        "validation_status": "passed",
        "validation_errors": [],
        "safety_flags": [],
        "candidate_payload": {
            "strategy_name": "ma_cross",
            "symbol": "000002",
            "parameters": {
                "short_window": 8,
                "long_window": 34,
                "order_size": 200,
            },
            "requires_human_approval": True,
        },
        "backtest_request_payload": {
            "job_type": "backtest_ma_cross",
            "payload": {
                "symbol": "000002",
                "short_window": 8,
                "long_window": 34,
                "order_size": 200,
                "initial_cash": "150000.50",
            },
        },
        "requires_human_approval": True,
    }


def test_missing_required_field_fails_without_candidate():
    spec = complete_ma_cross_spec()
    spec.pop("exit_rules")

    result = validate_strategy_candidate(spec, request_symbol="000001")

    assert result["validation_status"] == "failed"
    assert "missing field: exit_rules" in result["validation_errors"]
    assert result["candidate_payload"] is None
    assert result["backtest_request_payload"] is None
    assert result["requires_human_approval"] is True


def test_unknown_explicit_template_fails():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(strategy_template="grid"),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert result["validation_errors"] == ["unsupported strategy_template: grid"]
    assert result["candidate_payload"] is None


def test_missing_template_with_ma_cross_evidence_is_inferred():
    spec = complete_ma_cross_spec()
    spec.pop("strategy_template")

    result = validate_strategy_candidate(spec, request_symbol="000001")

    assert result["validation_status"] == "passed"
    assert result["candidate_payload"]["strategy_name"] == "ma_cross"


def test_missing_template_without_ma_cross_evidence_needs_review():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(
            strategy_template=None,
            entry_rules=["Enter when sentiment score improves."],
            exit_rules=["Exit when sentiment score weakens."],
            parameters_to_test={"lookback": 10},
        ),
        request_symbol="000001",
    )

    assert result["validation_status"] == "needs_review"
    assert result["validation_errors"] == [
        "strategy template is not explicit or safely inferable"
    ]
    assert result["candidate_payload"] is None
    assert result["backtest_request_payload"] is None


def test_code_like_content_sets_safety_flag_and_blocks_candidate():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(thesis="```python\ndef trade():\n    return 1\n```"),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert result["safety_flags"] == ["contains_executable_code"]
    assert result["candidate_payload"] is None


def test_broker_or_order_instruction_sets_safety_flag_and_blocks_candidate():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(risk_controls=["Place order through broker API after the signal."]),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert result["safety_flags"] == ["contains_broker_or_order_instruction"]
    assert result["candidate_payload"] is None


def test_profitability_claim_sets_safety_flag_and_blocks_candidate():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(thesis="This is a guaranteed return strategy."),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert result["safety_flags"] == ["contains_profitability_claim"]
    assert result["candidate_payload"] is None


def test_live_trading_recommendation_sets_safety_flag_and_blocks_candidate():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(backtest_readiness="Ready for live trading immediately."),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert result["safety_flags"] == ["contains_live_trading_recommendation"]
    assert result["candidate_payload"] is None


@pytest.mark.parametrize(
    ("parameters", "expected_error"),
    [
        ({"short_window": 0, "long_window": 20}, "short_window must be an integer greater than 0"),
        ({"short_window": 20, "long_window": 20}, "long_window must be greater than short_window"),
        ({"order_size": -1}, "order_size must be an integer greater than 0"),
        ({"initial_cash": "NaN"}, "initial_cash must be a finite decimal string greater than 0"),
    ],
)
def test_invalid_parameters_block_candidate(parameters, expected_error):
    result = validate_strategy_candidate(
        complete_ma_cross_spec(parameters_to_test=parameters),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert expected_error in result["validation_errors"]
    assert result["candidate_payload"] is None


def test_symbol_can_come_from_llm_spec_when_request_symbol_is_missing():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(symbol="600000"),
        request_symbol=None,
    )

    assert result["validation_status"] == "passed"
    assert result["backtest_request_payload"]["payload"]["symbol"] == "600000"


def test_missing_symbol_blocks_backtest_request():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(symbol=""),
        request_symbol=None,
    )

    assert result["validation_status"] == "failed"
    assert "missing symbol" in result["validation_errors"]
    assert result["backtest_request_payload"] is None
```

- [ ] **Step 2: Run the validator test file and verify it fails before implementation**

Run:

```bash
python -m pytest tests/unit/test_strategy_candidates.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'quant_trading.agents.candidates'`.

- [ ] **Step 3: Implement the candidate validator**

Create `src/quant_trading/agents/candidates.py` with this content:

```python
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

BACKTEST_MA_CROSS = "backtest_ma_cross"
SUPPORTED_TEMPLATE = "ma_cross"

VALIDATION_PASSED = "passed"
VALIDATION_FAILED = "failed"
VALIDATION_NEEDS_REVIEW = "needs_review"

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

DEFAULT_SHORT_WINDOW = 5
DEFAULT_LONG_WINDOW = 20
DEFAULT_ORDER_SIZE = 100
DEFAULT_INITIAL_CASH = "100000"

EXECUTABLE_PATTERNS = (
    r"```(?:python|py)?",
    r"\bdef\s+\w+\s*\(",
    r"\bclass\s+\w+\s*[:(]",
    r"\bimport\s+\w+",
    r"\bfrom\s+\w+\s+import\b",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"\bsubprocess\b",
    r"\bos\.system\s*\(",
    r"\b__import__\s*\(",
)

BROKER_OR_ORDER_PATTERNS = (
    r"\bbroker\s+api\b",
    r"\bexchange\s+(?:submission|api)\b",
    r"\bsubmit\s+(?:an?\s+)?order\b",
    r"\bplace\s+(?:an?\s+)?order\b",
    r"\bsend\s+(?:an?\s+)?order\b",
    r"\blive\s+order\b",
    r"\bbuy\s+now\b",
    r"\bsell\s+now\b",
    r"立即买入",
    r"立即卖出",
    r"真实下单",
)

PROFITABILITY_PATTERNS = (
    r"\bguaranteed\s+(?:profit|return)\b",
    r"\bguarantee\s+(?:profit|return)\b",
    r"\brisk-free\s+profit\b",
    r"\bcannot\s+lose\b",
    r"\bwill\s+make\s+money\b",
    r"稳赚",
    r"保证收益",
)

LIVE_TRADING_PATTERNS = (
    r"\blive\s+trading\b",
    r"\btrade\s+live\b",
    r"\breal-money\s+trading\b",
    r"\buse\s+this\s+strategy\s+live\b",
    r"实盘交易",
)


def validate_strategy_candidate(
    parsed_payload: dict[str, Any],
    *,
    request_symbol: str | None,
) -> dict[str, Any]:
    spec = parsed_payload if isinstance(parsed_payload, dict) else {}
    safety_flags = _detect_safety_flags(spec)
    validation_errors = _missing_field_errors(spec)

    template_status, template_error = _resolve_template(spec)
    if template_status == VALIDATION_FAILED:
        validation_errors.append(template_error)

    if safety_flags or validation_errors:
        return _empty_result(
            VALIDATION_FAILED,
            validation_errors=validation_errors,
            safety_flags=safety_flags,
        )

    if template_status == VALIDATION_NEEDS_REVIEW:
        return _empty_result(
            VALIDATION_NEEDS_REVIEW,
            validation_errors=[template_error],
            safety_flags=safety_flags,
        )

    parameters, parameter_errors = _extract_ma_cross_parameters(spec)
    symbol = _resolve_symbol(request_symbol, spec)
    if not symbol:
        parameter_errors.append("missing symbol")

    if parameter_errors:
        return _empty_result(
            VALIDATION_FAILED,
            validation_errors=parameter_errors,
            safety_flags=safety_flags,
        )

    short_window = parameters["short_window"]
    long_window = parameters["long_window"]
    order_size = parameters["order_size"]
    initial_cash = parameters["initial_cash"]
    candidate_payload = {
        "strategy_name": SUPPORTED_TEMPLATE,
        "symbol": symbol,
        "parameters": {
            "short_window": short_window,
            "long_window": long_window,
            "order_size": order_size,
        },
        "requires_human_approval": True,
    }
    backtest_request_payload = {
        "job_type": BACKTEST_MA_CROSS,
        "payload": {
            "symbol": symbol,
            "short_window": short_window,
            "long_window": long_window,
            "order_size": order_size,
            "initial_cash": initial_cash,
        },
    }
    return {
        "validation_status": VALIDATION_PASSED,
        "validation_errors": [],
        "safety_flags": [],
        "candidate_payload": candidate_payload,
        "backtest_request_payload": backtest_request_payload,
        "requires_human_approval": True,
    }


def _empty_result(
    validation_status: str,
    *,
    validation_errors: list[str],
    safety_flags: list[str],
) -> dict[str, Any]:
    return {
        "validation_status": validation_status,
        "validation_errors": validation_errors,
        "safety_flags": safety_flags,
        "candidate_payload": None,
        "backtest_request_payload": None,
        "requires_human_approval": True,
    }


def _missing_field_errors(spec: dict[str, Any]) -> list[str]:
    return [f"missing field: {field}" for field in REQUIRED_FIELDS if _is_missing(spec.get(field))]


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _resolve_template(spec: dict[str, Any]) -> tuple[str, str]:
    explicit = _first_present(spec, ("strategy_template", "template", "strategy_name"))
    if explicit is not None:
        normalized = _normalize_template(explicit)
        if normalized == SUPPORTED_TEMPLATE:
            return VALIDATION_PASSED, ""
        return VALIDATION_FAILED, f"unsupported strategy_template: {explicit}"

    if _has_ma_cross_evidence(spec):
        return VALIDATION_PASSED, ""
    return VALIDATION_NEEDS_REVIEW, "strategy template is not explicit or safely inferable"


def _normalize_template(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _has_ma_cross_evidence(spec: dict[str, Any]) -> bool:
    text = _flatten_text(spec).lower()
    has_cross = any(token in text for token in ("cross", "crossover", "golden cross", "death cross", "金叉", "死叉"))
    has_ma = (
        "moving average" in text
        or "均线" in text
        or re.search(r"\b(?:ma|sma|ema)\b", text) is not None
    )
    has_windows = (
        _find_first_key(spec, "short_window") is not None
        and _find_first_key(spec, "long_window") is not None
    )
    return has_cross and (has_ma or has_windows)


def _detect_safety_flags(spec: dict[str, Any]) -> list[str]:
    text = _flatten_text(spec).lower()
    flags: list[str] = []
    if _matches_any(text, EXECUTABLE_PATTERNS):
        flags.append("contains_executable_code")
    if _matches_any(text, BROKER_OR_ORDER_PATTERNS):
        flags.append("contains_broker_or_order_instruction")
    if _matches_any(text, PROFITABILITY_PATTERNS):
        flags.append("contains_profitability_claim")
    if _matches_any(text, LIVE_TRADING_PATTERNS):
        flags.append("contains_live_trading_recommendation")
    return flags


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _extract_ma_cross_parameters(spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    raw_short = _find_first_key(spec, "short_window")
    raw_long = _find_first_key(spec, "long_window")
    raw_order_size = _find_first_key(spec, "order_size")
    raw_initial_cash = _find_first_key(spec, "initial_cash")

    short_window, short_error = _positive_int(
        DEFAULT_SHORT_WINDOW if raw_short is None else raw_short,
        "short_window",
    )
    long_window, long_error = _positive_int(
        DEFAULT_LONG_WINDOW if raw_long is None else raw_long,
        "long_window",
    )
    order_size, order_size_error = _positive_int(
        DEFAULT_ORDER_SIZE if raw_order_size is None else raw_order_size,
        "order_size",
    )
    initial_cash, initial_cash_error = _positive_decimal_string(
        DEFAULT_INITIAL_CASH if raw_initial_cash is None else raw_initial_cash,
        "initial_cash",
    )

    errors = [
        error
        for error in (short_error, long_error, order_size_error, initial_cash_error)
        if error
    ]
    if short_window is not None and long_window is not None and long_window <= short_window:
        errors.append("long_window must be greater than short_window")

    return (
        {
            "short_window": short_window,
            "long_window": long_window,
            "order_size": order_size,
            "initial_cash": initial_cash,
        },
        errors,
    )


def _positive_int(value: Any, field_name: str) -> tuple[int | None, str | None]:
    if isinstance(value, bool):
        return None, f"{field_name} must be an integer greater than 0"
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        return None, f"{field_name} must be an integer greater than 0"
    if parsed <= 0:
        return None, f"{field_name} must be an integer greater than 0"
    return parsed, None


def _positive_decimal_string(value: Any, field_name: str) -> tuple[str | None, str | None]:
    raw = str(value).strip()
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None, f"{field_name} must be a finite decimal string greater than 0"
    if not parsed.is_finite() or parsed <= 0:
        return None, f"{field_name} must be a finite decimal string greater than 0"
    return format(parsed, "f"), None


def _resolve_symbol(request_symbol: str | None, spec: dict[str, Any]) -> str | None:
    request_value = (request_symbol or "").strip()
    if request_value:
        return request_value[:32]
    spec_value = _find_first_key(spec, "symbol")
    if spec_value is None:
        return None
    symbol = str(spec_value).strip()
    return symbol[:32] if symbol else None


def _first_present(spec: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = spec.get(key)
        if value is not None:
            return value
    return None


def _find_first_key(value: Any, target_key: str) -> Any:
    if isinstance(value, dict):
        if target_key in value:
            return value[target_key]
        for child in value.values():
            found = _find_first_key(child, target_key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first_key(child, target_key)
            if found is not None:
                return found
    return None


def _flatten_text(value: Any) -> str:
    parts: list[str] = []
    _collect_text(value, parts)
    return "\n".join(parts)


def _collect_text(value: Any, parts: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            parts.append(str(key))
            _collect_text(child, parts)
    elif isinstance(value, list):
        for child in value:
            _collect_text(child, parts)
    elif value is not None:
        parts.append(str(value))
```

- [ ] **Step 4: Run the validator tests and verify they pass**

Run:

```bash
python -m pytest tests/unit/test_strategy_candidates.py -q
```

Expected: PASS with all tests in `tests/unit/test_strategy_candidates.py` passing.

- [ ] **Step 5: Run the existing strategy idea unit tests**

Run:

```bash
python -m pytest tests/unit/test_strategy_idea_agent.py -q
```

Expected: PASS. The parser tests should remain unchanged because candidate validation is a separate module.

- [ ] **Step 6: Spec review**

Check:

```bash
rg -n "submit_job_run|Broker|PaperRun|run_ma_cross_backtest|MACrossStrategy" src/quant_trading/agents/candidates.py
```

Expected: no matches. The validator must not import or call execution paths.

- [ ] **Step 7: Quality review**

Check:

```bash
python -m py_compile src/quant_trading/agents/candidates.py tests/unit/test_strategy_candidates.py
```

Expected: PASS with no syntax errors.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/quant_trading/agents/candidates.py tests/unit/test_strategy_candidates.py
git commit -m "feat: add strategy candidate validator"
```

---

### Task 2: Strategy Idea Service Integration

**Files:**
- Modify: `src/quant_trading/agents/service.py`
- Modify: `tests/integration/test_agents_jobs.py`

- [ ] **Step 1: Add shared valid LLM payload fixture to integration tests**

In `tests/integration/test_agents_jobs.py`, add `import json` near the top and add this constant after imports:

```python
VALID_MA_CROSS_RESPONSE = json.dumps(
    {
        "strategy_template": "ma_cross",
        "thesis": "Trend continuation research with a moving-average crossover.",
        "market_regime_assumption": "Directional daily market with enough liquidity.",
        "entry_rules": [
            "Enter research long exposure when the short moving average crosses above the long moving average."
        ],
        "exit_rules": [
            "Exit research exposure when the short moving average crosses below the long moving average."
        ],
        "risk_controls": ["Fixed order size and drawdown review before paper trading."],
        "parameters_to_test": {
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
            "initial_cash": "100000",
        },
        "data_requirements": ["Daily OHLCV bars."],
        "failure_modes": ["Whipsaw in range-bound markets."],
        "backtest_readiness": "ready",
    },
    ensure_ascii=False,
)
```

- [ ] **Step 2: Update the service persistence test to expect a passed candidate**

Replace the fake LLM content in `test_run_strategy_idea_agent_persists_success()` with `VALID_MA_CROSS_RESPONSE` and add these assertions before the database row assertions end:

```python
    assert result["validation_status"] == "passed"
    assert result["validation_errors"] == []
    assert result["safety_flags"] == []
    assert result["candidate_payload"] == {
        "strategy_name": "ma_cross",
        "symbol": "000001",
        "parameters": {
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
        },
        "requires_human_approval": True,
    }
    assert result["backtest_request_payload"] == {
        "job_type": "backtest_ma_cross",
        "payload": {
            "symbol": "000001",
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
            "initial_cash": "100000",
        },
    }
    assert result["requires_human_approval"] is True
```

- [ ] **Step 3: Add an unparseable-text service test**

Add this test to `tests/integration/test_agents_jobs.py`:

```python
def test_run_strategy_idea_agent_marks_unparseable_text_needs_review():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    result = run_strategy_idea_agent(
        engine,
        StrategyIdeaRequest(idea="Trend following", symbol="000001"),
        llm_client=FakeLLMClient("plain narrative response"),
        job_run_id=5,
    )

    assert result["parsed"] is False
    assert result["validation_status"] == "needs_review"
    assert result["validation_errors"] == []
    assert result["safety_flags"] == []
    assert result["candidate_payload"] is None
    assert result["backtest_request_payload"] is None
    assert result["requires_human_approval"] is True
```

- [ ] **Step 4: Update the strategy idea job API test**

In `test_strategy_idea_job_api_submits_agent_job()`, replace the `FakeLLMClient(...)` content with `FakeLLMClient(VALID_MA_CROSS_RESPONSE)` and add:

```python
    assert payload["result_payload"]["validation_status"] == "passed"
    assert payload["result_payload"]["candidate_payload"]["strategy_name"] == "ma_cross"
    assert payload["result_payload"]["backtest_request_payload"]["job_type"] == "backtest_ma_cross"
    assert payload["result_payload"]["requires_human_approval"] is True
```

- [ ] **Step 5: Add a trading-row safety invariant integration test**

Add this test to `tests/integration/test_agents_jobs.py`:

```python
def test_strategy_idea_candidate_job_does_not_create_trading_rows(monkeypatch):
    from quant_trading.jobs import runtime as runtime_module
    from quant_trading.storage.models import BacktestRunORM, BrokerOrderEventORM, PaperRunORM

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient(VALID_MA_CROSS_RESPONSE),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    response = client.post(
        "/jobs/agents/strategy-idea",
        json={"idea": "Research moving average crossover", "symbol": "000001"},
    )

    assert response.status_code == 200
    assert response.json()["result_payload"]["validation_status"] == "passed"
    with session_scope(engine) as session:
        assert session.query(BacktestRunORM).count() == 0
        assert session.query(PaperRunORM).count() == 0
        assert session.query(BrokerOrderEventORM).count() == 0
```

- [ ] **Step 6: Run integration tests and verify they fail before service integration**

Run:

```bash
python -m pytest tests/integration/test_agents_jobs.py -q
```

Expected: FAIL on missing `validation_status`, `candidate_payload`, or `backtest_request_payload` in strategy idea results.

- [ ] **Step 7: Integrate validator into service**

In `src/quant_trading/agents/service.py`, add this import:

```python
from quant_trading.agents.candidates import validate_strategy_candidate
```

Then replace the `parsed_payload` and `result_payload` construction block inside `run_strategy_idea_agent()` with:

```python
        parsed_payload = parse_strategy_idea_response(
            response.content[: settings.agent_result_max_chars]
        )
        if parsed_payload["parsed"]:
            validation_payload = validate_strategy_candidate(
                parsed_payload["spec"],
                request_symbol=clean_request.symbol,
            )
        else:
            validation_payload = {
                "validation_status": "needs_review",
                "validation_errors": [],
                "safety_flags": [],
                "candidate_payload": None,
                "backtest_request_payload": None,
                "requires_human_approval": True,
            }
        result_payload = {
            "agent_run_id": agent_run_id,
            "agent_type": AGENT_STRATEGY_IDEA,
            "symbol": clean_request.symbol,
            "research_only": True,
            "disclaimer": RESEARCH_DISCLAIMER,
            **parsed_payload,
            **validation_payload,
        }
```

- [ ] **Step 8: Run targeted integration tests and verify they pass**

Run:

```bash
python -m pytest tests/integration/test_agents_jobs.py -q
```

Expected: PASS.

- [ ] **Step 9: Run targeted agent API tests**

Run:

```bash
python -m pytest tests/integration/test_agents_api.py -q
```

Expected: PASS. Existing `/agent-runs/{agent_run_id}` read shape should continue returning persisted `result_payload`.

- [ ] **Step 10: Spec review**

Check:

```bash
rg -n "submit_job_run|run_ma_cross_backtest|PAPER_RUN_TICK|BrokerOrderEventORM" src/quant_trading/agents src/quant_trading/jobs/runtime.py
```

Expected:
- `run_ma_cross_backtest` and `PAPER_RUN_TICK` appear only in existing job runtime paths.
- `BrokerOrderEventORM` does not appear under `src/quant_trading/agents`.
- `submit_job_run` does not appear under `src/quant_trading/agents`.

- [ ] **Step 11: Quality review**

Check:

```bash
python -m py_compile src/quant_trading/agents/service.py tests/integration/test_agents_jobs.py
```

Expected: PASS with no syntax errors.

- [ ] **Step 12: Commit Task 2**

```bash
git add src/quant_trading/agents/service.py tests/integration/test_agents_jobs.py
git commit -m "feat: validate strategy idea candidates"
```

---

### Task 3: Documentation Update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README Quant Agent section**

Rename `## Quant Agent v1` to `## Quant Agent` and replace the opening paragraph in that section with:

```markdown
Quant Agent adds audited research agents for market analysis and strategy idea structuring.
Agents run through the existing job runtime and store business-level audit rows in `agent_runs`.

Strategy idea jobs now validate parsed LLM specs as research candidates. V2 supports only the
existing `ma_cross` template and produces a suggested `backtest_ma_cross` request payload when the
spec is complete, safe, and mapped to the whitelist. The request payload is a suggestion only:
operators must submit any backtest explicitly through `/jobs/backtests/ma-cross` or
`/workflows/backtests/ma-cross`.
```

In the same section, replace the final safety paragraph with:

```markdown
Agent outputs are research-only. They do not place orders, call broker adapters, approve strategies,
execute generated code, start paper runs, submit backtests automatically, or provide buy/sell
instructions. Strategy-code generation and automatic trading are intentionally outside this
milestone. Candidate payloads always require human approval.
```

- [ ] **Step 2: Add a short candidate response note after the strategy idea curl**

Add this paragraph after the strategy idea job curl example:

```markdown
When validation passes, the job result includes `validation_status="passed"`,
`candidate_payload.strategy_name="ma_cross"`, and a `backtest_request_payload` shaped for the
existing MA Cross backtest job. When validation fails or needs review, candidate and backtest
request payloads are `null` while the agent run remains auditable.
```

- [ ] **Step 3: Verify README mentions the key product boundaries**

Run:

```bash
rg -n "Quant Agent|validation_status|ma_cross|backtest_request_payload|human approval|research-only|submit backtests automatically" README.md
```

Expected: all key phrases are present.

- [ ] **Step 4: Spec review**

Check the README against the Documentation section of the spec:

```bash
rg -n "ma_cross|suggestion only|explicitly|research-only|human approval" README.md
```

Expected: README documents `ma_cross`-only support, explicit operator submission, research-only output, and human approval.

- [ ] **Step 5: Quality review**

Check for accidental live-trading language:

```bash
rg -n "place real|live trading|automatic trading|broker" README.md
```

Expected: any matches describe boundaries or non-goals, not enabled behavior.

- [ ] **Step 6: Commit Task 3**

```bash
git add README.md
git commit -m "docs: document quant agent candidate validation"
```

---

### Task 4: Final Verification And Safety Audit

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run targeted agent tests**

```bash
python -m pytest tests/unit/test_strategy_candidates.py tests/unit/test_strategy_idea_agent.py tests/integration/test_agents_jobs.py tests/integration/test_agents_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full test suite**

```bash
python -m pytest tests -q
```

Expected: PASS.

- [ ] **Step 3: Compile changed Python files**

```bash
python -m py_compile src/quant_trading/agents/candidates.py src/quant_trading/agents/service.py tests/unit/test_strategy_candidates.py tests/integration/test_agents_jobs.py
```

Expected: PASS.

- [ ] **Step 4: Check whitespace and patch cleanliness**

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 5: Check no DeepSeek key can be stored by agent job payloads**

```bash
rg -n "deepseek_api_key|DEEPSEEK_API_KEY" src/quant_trading tests
```

Expected:
- `deepseek_api_key` appears only in config and LLM-client credential handling.
- `DEEPSEEK_API_KEY` may appear in credential error-message assertions.
- Job request payload helpers do not serialize `DEEPSEEK_API_KEY`.

- [ ] **Step 6: Check candidate layer cannot submit execution**

```bash
rg -n "submit_job_run|WorkflowCommandRunner|run_ma_cross_backtest|run_paper_tick|Broker|PaperRun|BacktestRun" src/quant_trading/agents
```

Expected:
- No matches in `src/quant_trading/agents/candidates.py`.
- Existing agent service should not call `submit_job_run`, `run_ma_cross_backtest`, `run_paper_tick`, or broker adapters.

- [ ] **Step 7: Spec review**

Confirm every spec requirement has a matching passing test or documentation update:

- valid `ma_cross` spec creates candidate and backtest request.
- missing required fields fail.
- unknown explicit template fails.
- unclear inferred template returns `needs_review`.
- executable code, broker/order wording, profitability claims, and live-trading recommendations are flagged.
- invalid parameters fail.
- unparseable LLM text returns `parsed=False` and `validation_status="needs_review"`.
- service and job API persist candidate payloads.
- candidate jobs do not create `backtest_runs`, `paper_runs`, or `broker_order_events`.
- README documents `ma_cross`-only candidate validation and explicit operator backtest submission.

- [ ] **Step 8: Quality review**

Inspect the final diff:

```bash
git diff --stat HEAD~3..HEAD
git diff HEAD~3..HEAD -- src/quant_trading/agents/candidates.py src/quant_trading/agents/service.py tests/unit/test_strategy_candidates.py tests/integration/test_agents_jobs.py README.md
```

Expected:
- No schema migration files.
- No new endpoint files.
- No broker, paper, or backtest execution call inside agent validation.
- No unrelated formatting churn.

- [ ] **Step 9: Push branch when requested**

```bash
git status --short --branch
git push origin codex/quant-agent-v2-candidate-validation
```

Expected: branch pushes cleanly after user asks to push.
