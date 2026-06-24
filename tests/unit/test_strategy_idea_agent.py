from quant_trading.agents.models import StrategyIdeaRequest
from quant_trading.agents.strategy_idea import (
    build_strategy_idea_prompt,
    parse_strategy_idea_response,
)


def test_strategy_idea_prompt_contains_safety_constraints():
    prompt = build_strategy_idea_prompt(
        StrategyIdeaRequest(
            idea="Use moving averages to capture trend continuation",
            symbol="000001",
            market_context="A-share daily bars",
            constraints={"long_only": True},
        ),
        max_chars=8000,
    )

    assert "Do not output executable code" in prompt
    assert "Do not provide live trading instructions" in prompt
    assert "Do not claim profitability" in prompt
    assert "JSON object" in prompt
    assert "entry_rules" in prompt


def test_parse_strategy_idea_response_parses_json_object():
    parsed = parse_strategy_idea_response(
        """{"thesis":"trend","entry_rules":["ma cross"],"exit_rules":["reverse"],"risk_controls":["max loss"],"parameters_to_test":["window"],"data_requirements":["daily bars"],"failure_modes":["chop"],"backtest_readiness":"ready"}"""
    )

    assert parsed["parsed"] is True
    assert parsed["spec"]["thesis"] == "trend"
    assert parsed["spec"]["entry_rules"] == ["ma cross"]


def test_parse_strategy_idea_response_falls_back_to_bounded_narrative():
    parsed = parse_strategy_idea_response("plain narrative")

    assert parsed == {"parsed": False, "narrative": "plain narrative"}
