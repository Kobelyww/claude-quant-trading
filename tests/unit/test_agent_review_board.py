import json

from quant_trading.agents.output_safety import contains_unsafe_agent_text
from quant_trading.agents.review_board import (
    ReviewBoardVote,
    coordinator_recommendation,
    parse_reviewer_vote,
)


def test_parse_reviewer_vote_falls_back_to_needs_review_on_invalid_json():
    vote = parse_reviewer_vote("not json", reviewer_role="risk_officer")
    assert vote.vote == "needs_review"
    assert vote.reason_code == "invalid_reviewer_output"


def test_coordinator_caps_not_ready_floor_to_needs_more_research():
    result = coordinator_recommendation(
        votes=[ReviewBoardVote("validation_reviewer", "pass", "ok", "looks fine", {})],
        readiness_floor="not_ready",
        data_quality_status="passed",
    )
    assert result.final_recommendation == "needs_more_research"


def test_coordinator_caps_running_floor_to_needs_more_research():
    result = coordinator_recommendation(
        votes=[
            ReviewBoardVote(
                "validation_reviewer",
                "pass",
                "validation_passed",
                "looks fine",
                {},
            )
        ],
        readiness_floor="running",
        data_quality_status="passed",
    )
    assert result.final_recommendation == "needs_more_research"
    assert "readiness_floor_not_ready" not in result.blocking_reason_codes
    assert "readiness_floor_unknown_or_in_progress" in result.blocking_reason_codes


def test_coordinator_caps_unknown_floor_to_needs_more_research():
    result = coordinator_recommendation(
        votes=[
            ReviewBoardVote(
                "validation_reviewer",
                "pass",
                "validation_passed",
                "clear",
                {},
            )
        ],
        readiness_floor="experimental",
        data_quality_status="passed",
    )
    assert result.final_recommendation == "needs_more_research"
    assert "readiness_floor_unknown_or_in_progress" in result.blocking_reason_codes


def test_coordinator_rejects_failed_data_quality():
    result = coordinator_recommendation(
        votes=[ReviewBoardVote("strategy_researcher", "pass", "ok", "clear", {})],
        readiness_floor="ready_for_paper_research",
        data_quality_status="failed",
    )
    assert result.final_recommendation == "reject"
    assert "data_quality_failed" in result.blocking_reason_codes


def test_parse_reviewer_vote_rejects_unsupported_vote():
    vote = parse_reviewer_vote(
        '{"vote":"approve","reason_code":"ok","rationale":"clear","evidence":{}}',
        reviewer_role="strategy_researcher",
    )
    assert vote.vote == "needs_review"
    assert vote.reason_code == "invalid_reviewer_output"


def test_parse_reviewer_vote_rejects_unsafe_rationale():
    vote = parse_reviewer_vote(
        (
            '{"vote":"pass","reason_code":"ok",'
            '"rationale":"place a live order tomorrow","evidence":{}}'
        ),
        reviewer_role="risk_officer",
    )
    assert vote.vote == "needs_review"
    assert vote.reason_code == "unsafe_reviewer_output"


def test_parse_reviewer_vote_rejects_unsafe_evidence():
    vote = parse_reviewer_vote(
        json.dumps(
            {
                "vote": "pass",
                "reason_code": "ok",
                "rationale": "clear",
                "evidence": {
                    "snippet": "```python\nplace_live_order('000001')\n```",
                },
            }
        ),
        reviewer_role="risk_officer",
    )
    assert vote.vote == "needs_review"
    assert vote.reason_code == "unsafe_reviewer_output"
    assert vote.evidence == {}


def test_parse_reviewer_vote_rejects_unsafe_evidence_after_long_benign_field():
    vote = parse_reviewer_vote(
        json.dumps(
            {
                "vote": "pass",
                "reason_code": "ok",
                "rationale": "clear",
                "evidence": {
                    "benign_context": "research-only notes " * 300,
                    "unsafe_followup": "```python\nplace_live_order('000001')\n```",
                },
            }
        ),
        reviewer_role="risk_officer",
    )
    assert vote.vote == "needs_review"
    assert vote.reason_code == "unsafe_reviewer_output"
    assert vote.evidence == {}


def test_coordinator_all_pass_ready_for_paper_research_consideration_is_research_only():
    result = coordinator_recommendation(
        votes=[
            ReviewBoardVote("data_steward", "pass", "ok", "clear", {}),
            ReviewBoardVote("strategy_researcher", "pass", "ok", "clear", {}),
            ReviewBoardVote("risk_officer", "pass", "ok", "clear", {}),
            ReviewBoardVote("validation_reviewer", "pass", "ok", "clear", {}),
            ReviewBoardVote("operations_reviewer", "pass", "ok", "clear", {}),
        ],
        readiness_floor="ready_for_paper_research",
        data_quality_status="passed",
    )
    assert result.final_recommendation == "ready_for_paper_research_consideration"
    assert not contains_unsafe_agent_text([result.summary["coordinator_rationale"]])


def test_coordinator_block_vote_caps_to_needs_more_research():
    result = coordinator_recommendation(
        votes=[
            ReviewBoardVote(
                "validation_reviewer",
                "block",
                "walk_forward_failed",
                "needs more evidence",
                {},
            )
        ],
        readiness_floor="ready_for_paper_research",
        data_quality_status="passed",
    )
    assert result.final_recommendation == "needs_more_research"
    assert "walk_forward_failed" in result.blocking_reason_codes
