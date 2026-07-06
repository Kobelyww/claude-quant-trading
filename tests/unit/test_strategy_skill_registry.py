from quant_trading.agents.skills import StrategySkillRegistry, default_ma_cross_skill


def test_default_ma_cross_skill_payload_matches_seed_contract():
    skill = default_ma_cross_skill()
    assert skill.skill_key == "ma_cross"
    assert skill.version == "1.0.0"
    assert skill.status == "active"
    assert "short_window" in skill.parameter_schema
    assert "long_window" in skill.parameter_schema


def test_registry_validates_ma_cross_candidate_and_preserves_backtest_payload():
    registry = StrategySkillRegistry.from_defaults()
    result = registry.validate_candidate(
        {
            "strategy_skill_key": "ma_cross",
            "strategy_skill_version": "1.0.0",
            "thesis": "Research a moving-average crossover regime.",
            "market_regime_assumption": "Trending market.",
            "entry_rules": {"short_window": 5, "long_window": 20},
            "exit_rules": {"short_window": 5, "long_window": 20},
            "risk_controls": ["max order size"],
            "parameters_to_test": {
                "short_window": 5,
                "long_window": 20,
                "order_size": 100,
                "initial_cash": "100000",
            },
            "data_requirements": ["daily OHLCV"],
            "failure_modes": ["sideways whipsaw"],
            "backtest_readiness": "ready",
        },
        request_symbol="000001",
    )

    assert result.validation_status == "passed"
    assert result.candidate_payload["strategy_name"] == "ma_cross"
    assert result.candidate_payload["strategy_skill_key"] == "ma_cross"
    assert result.backtest_request_payload["job_type"] == "backtest_ma_cross"
    assert result.backtest_request_payload["payload"]["initial_cash"] == "100000"


def test_registry_rejects_unsupported_skill_with_safety_flags_without_backtest_payload():
    registry = StrategySkillRegistry.from_defaults()
    result = registry.validate_candidate(
        {
            "strategy_skill_key": "arbitrary_python",
            "thesis": "run generated code\n```python\ndef trade():\n    return 1\n```",
        },
        request_symbol="000001",
    )

    assert result.validation_status == "failed"
    assert "unsupported strategy_skill_key: arbitrary_python" in result.validation_errors
    assert "contains_executable_code" in result.safety_flags
    assert result.candidate_payload is None
    assert result.backtest_request_payload is None
