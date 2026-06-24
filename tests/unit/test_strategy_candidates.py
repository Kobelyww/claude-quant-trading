from decimal import Decimal

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


@pytest.mark.parametrize("template_key", ["template", "strategy_name"])
def test_template_aliases_accept_ma_cross(template_key):
    spec = complete_ma_cross_spec()
    spec.pop("strategy_template")
    spec[template_key] = "ma_cross"

    result = validate_strategy_candidate(spec, request_symbol="000001")

    assert result["validation_status"] == "passed"
    assert result["candidate_payload"]["strategy_name"] == "ma_cross"


def test_missing_template_with_ma_cross_evidence_is_inferred():
    spec = complete_ma_cross_spec()
    spec.pop("strategy_template")
    spec["entry_rules"] = [
        "Enter research long exposure when the short moving average crossover is bullish."
    ]
    spec["exit_rules"] = ["Exit research exposure when the moving average cross reverses."]

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


def test_inference_requires_real_cross_term_with_window_parameters():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(
            strategy_template=None,
            entry_rules=["Enter across market regimes when trend strength improves."],
            exit_rules=["Exit across market regimes when trend strength weakens."],
            parameters_to_test={"short_window": 8, "long_window": 34},
        ),
        request_symbol="000001",
    )

    assert result["validation_status"] == "needs_review"
    assert result["validation_errors"] == [
        "strategy template is not explicit or safely inferable"
    ]
    assert result["candidate_payload"] is None


def test_inference_ignores_ma_substrings_inside_other_words():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(
            strategy_template=None,
            entry_rules=["Enter when signals cross during calmer market conditions."],
            exit_rules=["Exit when signals cross back in market stress."],
            parameters_to_test={"lookback": 10},
        ),
        request_symbol="000001",
    )

    assert result["validation_status"] == "needs_review"
    assert result["candidate_payload"] is None


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
        complete_ma_cross_spec(
            risk_controls=["Place order through broker API after the signal."]
        ),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert result["safety_flags"] == ["contains_broker_or_order_instruction"]
    assert result["candidate_payload"] is None


@pytest.mark.parametrize(
    "instruction",
    [
        "buy at market after the signal",
        "sell at open if price weakens",
        "execute buy order through the broker",
    ],
)
def test_direct_buy_sell_and_broker_order_terms_set_safety_flag(instruction):
    result = validate_strategy_candidate(
        complete_ma_cross_spec(risk_controls=[instruction]),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert "contains_broker_or_order_instruction" in result["safety_flags"]
    assert result["candidate_payload"] is None


def test_profitability_claim_sets_safety_flag_and_blocks_candidate():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(thesis="This is a guaranteed return strategy."),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert result["safety_flags"] == ["contains_profitability_claim"]
    assert result["candidate_payload"] is None


@pytest.mark.parametrize(
    "claim",
    [
        "guarantees returns",
        "promise 20% annual return",
        "100% win rate",
    ],
)
def test_profitability_claim_variants_set_safety_flag(claim):
    result = validate_strategy_candidate(
        complete_ma_cross_spec(thesis=claim),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert "contains_profitability_claim" in result["safety_flags"]
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
    "recommendation",
    [
        "must buy tomorrow",
        "start trading this live",
        "deploy to real account",
    ],
)
def test_live_trading_recommendation_variants_set_safety_flag(recommendation):
    result = validate_strategy_candidate(
        complete_ma_cross_spec(backtest_readiness=recommendation),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert "contains_live_trading_recommendation" in result["safety_flags"]
    assert result["candidate_payload"] is None


def test_multiple_safety_flags_preserve_required_order():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(
            thesis="```python\nimport os\n``` guaranteed return",
            risk_controls=["Place order through broker API after the signal."],
            backtest_readiness="Ready for live trading immediately.",
        ),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert result["safety_flags"] == [
        "contains_executable_code",
        "contains_broker_or_order_instruction",
        "contains_profitability_claim",
        "contains_live_trading_recommendation",
    ]
    assert result["candidate_payload"] is None


def test_nested_safety_scan_blocks_candidate():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(
            risk_controls=[
                {
                    "execution_notes": [
                        {"operator_instruction": "Send order through exchange API."}
                    ]
                }
            ]
        ),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert result["safety_flags"] == ["contains_broker_or_order_instruction"]
    assert result["candidate_payload"] is None


@pytest.mark.parametrize(
    ("parameters", "expected_error"),
    [
        (
            {"short_window": 0, "long_window": 20},
            "short_window must be an integer greater than 0",
        ),
        (
            {"short_window": 20, "long_window": 20},
            "long_window must be greater than short_window",
        ),
        ({"order_size": -1}, "order_size must be an integer greater than 0"),
        (
            {"initial_cash": "NaN"},
            "initial_cash must be a finite decimal string greater than 0",
        ),
        (
            {"short_window": True, "long_window": 20},
            "short_window must be an integer greater than 0",
        ),
        ({"order_size": False}, "order_size must be an integer greater than 0"),
        (
            {"initial_cash": True},
            "initial_cash must be a finite decimal string greater than 0",
        ),
        (
            {"initial_cash": 100000},
            "initial_cash must be a finite decimal string greater than 0",
        ),
        (
            {"initial_cash": Decimal("100000")},
            "initial_cash must be a finite decimal string greater than 0",
        ),
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


def test_parameter_defaults_when_supported_parameters_are_missing():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(parameters_to_test={"notes": "Use MA cross research."}),
        request_symbol="000001",
    )

    assert result["validation_status"] == "passed"
    assert result["candidate_payload"]["parameters"] == {
        "short_window": 5,
        "long_window": 20,
        "order_size": 100,
    }
    assert result["backtest_request_payload"]["payload"]["initial_cash"] == "100000"


def test_nested_parameters_outside_parameters_to_test_are_found():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(
            parameters_to_test={"notes": "Use moving average cross research."},
            research_config={
                "parameters": {
                    "short_window": 13,
                    "long_window": 55,
                    "order_size": 300,
                    "initial_cash": "250000.00",
                }
            },
        ),
        request_symbol="000001",
    )

    assert result["validation_status"] == "passed"
    assert result["candidate_payload"]["parameters"] == {
        "short_window": 13,
        "long_window": 55,
        "order_size": 300,
    }
    assert result["backtest_request_payload"]["payload"]["initial_cash"] == "250000.00"


def test_initial_cash_accepts_decimal_string():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(parameters_to_test={"initial_cash": "100000"}),
        request_symbol="000001",
    )

    assert result["validation_status"] == "passed"
    assert result["backtest_request_payload"]["payload"]["initial_cash"] == "100000"


def test_symbol_can_come_from_llm_spec_when_request_symbol_is_missing():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(symbol="600000"),
        request_symbol=None,
    )

    assert result["validation_status"] == "passed"
    assert result["backtest_request_payload"]["payload"]["symbol"] == "600000"


def test_symbol_is_stripped_capped_and_request_takes_precedence():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(symbol="600000"),
        request_symbol="  12345678901234567890123456789012345  ",
    )

    assert result["validation_status"] == "passed"
    assert (
        result["backtest_request_payload"]["payload"]["symbol"]
        == "12345678901234567890123456789012"
    )


def test_blank_request_symbol_falls_back_to_spec_symbol():
    result = validate_strategy_candidate(
        complete_ma_cross_spec(symbol="  600000  "),
        request_symbol="   ",
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
    assert result["candidate_payload"] is None
    assert result["backtest_request_payload"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("thesis", "   "),
        ("market_regime_assumption", None),
        ("entry_rules", []),
        ("risk_controls", {}),
    ],
)
def test_blank_none_and_empty_collection_required_fields_fail(field, value):
    result = validate_strategy_candidate(
        complete_ma_cross_spec(**{field: value}),
        request_symbol="000001",
    )

    assert result["validation_status"] == "failed"
    assert f"missing field: {field}" in result["validation_errors"]
    assert result["candidate_payload"] is None
    assert result["backtest_request_payload"] is None
