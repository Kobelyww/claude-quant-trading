import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from quant_trading.agents.backtest_review import (
    build_backtest_review_prompt,
    load_backtest_review_context,
    parse_backtest_review_response,
)
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    BacktestEquityPointORM,
    BacktestOrderORM,
    BacktestRunORM,
)
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentRunRepository,
)


def test_backtest_review_prompt_contains_safety_constraints_and_context():
    context = {
        "candidate_review": {"id": 7, "status": "backtest_succeeded"},
        "backtest_run": {"id": 11, "status": "done"},
        "metrics": {
            "symbol": "000001",
            "strategy_name": "ma_cross",
            "initial_cash": "100000.000000",
            "final_equity": "102000.000000",
            "absolute_pnl": "2000.000000",
            "return_pct": "2.000000",
            "status": "done",
        },
    }

    prompt = build_backtest_review_prompt(context, max_chars=8000)

    assert "do not claim future profitability" in prompt
    assert "do not give live trading instructions" in prompt
    assert "do not approve paper trading" in prompt
    assert "do not call brokers or exchanges" in prompt
    assert "do not output executable code" in prompt
    assert "do not provide buy or sell instructions" in prompt
    assert "summary" in prompt
    assert "risk_flags" in prompt
    assert "overfit_warnings" in prompt
    assert "paper_trading_readiness" in prompt
    assert "recommended_next_steps" in prompt
    assert "not_ready" in prompt
    assert "needs_review" in prompt
    assert "ready_for_paper_research" in prompt
    assert '"candidate_review"' in prompt
    assert '"absolute_pnl": "2000.000000"' in prompt


def test_parse_backtest_review_response_parses_allowed_json_shape():
    parsed = parse_backtest_review_response(
        json.dumps(
            {
                "summary": "Backtest was positive but narrow.",
                "risk_flags": ["small_sample"],
                "overfit_warnings": ["single_symbol"],
                "paper_trading_readiness": "ready_for_paper_research",
                "recommended_next_steps": ["run out-of-sample checks"],
            }
        ),
        candidate_review_id=7,
        backtest_run_id=11,
    )

    assert parsed == {
        "candidate_review_id": 7,
        "backtest_run_id": 11,
        "review_status": "completed",
        "research_only": True,
        "summary": "Backtest was positive but narrow.",
        "risk_flags": ["small_sample"],
        "overfit_warnings": ["single_symbol"],
        "paper_trading_readiness": "ready_for_paper_research",
        "recommended_next_steps": ["run out-of-sample checks"],
    }


def test_parse_backtest_review_response_forces_invalid_readiness_to_needs_review():
    parsed = parse_backtest_review_response(
        json.dumps(
            {
                "summary": "Looks ready.",
                "risk_flags": [],
                "overfit_warnings": [],
                "paper_trading_readiness": "approved_for_live_trading",
                "recommended_next_steps": ["start paper trading"],
            }
        ),
        candidate_review_id=7,
        backtest_run_id=11,
    )

    assert parsed["review_status"] == "needs_review"
    assert parsed["research_only"] is True
    assert parsed["paper_trading_readiness"] == "needs_review"
    assert "invalid paper_trading_readiness" in parsed["summary"]
    assert parsed["recommended_next_steps"] == [
        "review the backtest output manually before any further research action"
    ]


def test_parse_backtest_review_response_sanitizes_dangerous_structured_text():
    parsed = parse_backtest_review_response(
        json.dumps(
            {
                "summary": "Start paper trading now and buy 000001 through your broker.",
                "risk_flags": ["call broker to submit live order"],
                "overfit_warnings": ["buy 000001 after open"],
                "paper_trading_readiness": "approved_for_live_trading",
                "recommended_next_steps": [
                    "start paper trading",
                    "buy 000001",
                    "call broker and submit live order",
                ],
            }
        ),
        candidate_review_id=7,
        backtest_run_id=11,
    )

    serialized = json.dumps(parsed, ensure_ascii=False).lower()
    assert parsed["review_status"] == "needs_review"
    assert parsed["research_only"] is True
    assert parsed["paper_trading_readiness"] == "needs_review"
    assert parsed["risk_flags"] == ["unsafe_structured_review_output"]
    assert parsed["overfit_warnings"] == []
    assert parsed["recommended_next_steps"] == [
        "review the backtest output manually before any further research action"
    ]
    assert "invalid paper_trading_readiness" in parsed["summary"]
    assert "unsafe trading or paper/order instruction text" in parsed["summary"]
    assert "start paper trading" not in serialized
    assert "buy 000001" not in serialized
    assert "broker" not in serialized
    assert "live order" not in serialized


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "buy",
        "sell.",
        "buying",
        "selling",
        "create a paper trading run",
        "paper-trading is ready",
        "submit market orders after review",
        "live market order after review",
        "live trade after review",
        "execute trade now",
        "place trade tomorrow",
        "connect brokerage account",
    ],
)
def test_parse_backtest_review_response_sanitizes_unsafe_text_variants(unsafe_text):
    parsed = parse_backtest_review_response(
        json.dumps(
            {
                "summary": "Manual review needed.",
                "risk_flags": [],
                "overfit_warnings": [],
                "paper_trading_readiness": "ready_for_paper_research",
                "recommended_next_steps": [unsafe_text],
            }
        ),
        candidate_review_id=7,
        backtest_run_id=11,
    )

    unsafe_text_lower = unsafe_text.lower()
    fields = [
        parsed["summary"],
        *parsed["recommended_next_steps"],
        *parsed["risk_flags"],
        *parsed["overfit_warnings"],
    ]
    serialized_fields = json.dumps(fields, ensure_ascii=False).lower()
    assert parsed["review_status"] == "needs_review"
    assert parsed["paper_trading_readiness"] == "needs_review"
    assert parsed["research_only"] is True
    assert unsafe_text_lower not in serialized_fields


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "buy 000001 now",
        "execute trade now",
        "connect brokerage account",
    ],
)
def test_parse_backtest_review_response_sanitizes_unsafe_fallback_content(unsafe_text):
    parsed = parse_backtest_review_response(
        unsafe_text,
        candidate_review_id=7,
        backtest_run_id=11,
    )

    serialized = json.dumps(parsed, ensure_ascii=False).lower()
    assert parsed["review_status"] == "needs_review"
    assert parsed["research_only"] is True
    assert parsed["paper_trading_readiness"] == "needs_review"
    assert parsed["summary"] == "unstructured review output contained unsafe trading instruction text"
    assert parsed["recommended_next_steps"] == [
        "review the backtest output manually before any further research action"
    ]
    assert unsafe_text.lower() not in serialized


@pytest.mark.parametrize(
    "unsafe_readiness",
    [
        "buy",
        "sell.",
        "create a paper trading run",
        "submit market orders after review",
        "live market order after review",
    ],
)
def test_parse_backtest_review_response_sanitizes_unsafe_readiness_values(
    unsafe_readiness,
):
    parsed = parse_backtest_review_response(
        json.dumps(
            {
                "summary": "Manual review needed.",
                "risk_flags": [],
                "overfit_warnings": [],
                "paper_trading_readiness": unsafe_readiness,
                "recommended_next_steps": ["run more research diagnostics"],
            }
        ),
        candidate_review_id=7,
        backtest_run_id=11,
    )

    fields = [
        parsed["summary"],
        *parsed["recommended_next_steps"],
        *parsed["risk_flags"],
        *parsed["overfit_warnings"],
    ]
    serialized_fields = json.dumps(fields, ensure_ascii=False).lower()
    assert parsed["review_status"] == "needs_review"
    assert parsed["paper_trading_readiness"] == "needs_review"
    assert parsed["research_only"] is True
    assert unsafe_readiness.lower() not in serialized_fields


def test_parse_backtest_review_response_falls_back_for_unstructured_content():
    parsed = parse_backtest_review_response(
        "This is a narrative review, not JSON." * 100,
        candidate_review_id=7,
        backtest_run_id=11,
    )

    assert parsed["candidate_review_id"] == 7
    assert parsed["backtest_run_id"] == 11
    assert parsed["review_status"] == "needs_review"
    assert parsed["research_only"] is True
    assert parsed["risk_flags"] == ["unstructured_review_output"]
    assert parsed["overfit_warnings"] == []
    assert parsed["paper_trading_readiness"] == "needs_review"
    assert parsed["recommended_next_steps"] == [
        "review the backtest output manually before any further research action"
    ]
    assert len(parsed["summary"]) <= 500


def test_parse_backtest_review_response_falls_back_for_non_dict_json():
    parsed = parse_backtest_review_response(
        '["not", "an", "object"]',
        candidate_review_id=7,
        backtest_run_id=11,
    )

    assert parsed["review_status"] == "needs_review"
    assert parsed["risk_flags"] == ["unstructured_review_output"]
    assert parsed["paper_trading_readiness"] == "needs_review"


def test_parse_backtest_review_response_caps_structured_list_lengths():
    parsed = parse_backtest_review_response(
        json.dumps(
            {
                "summary": "Many diagnostics.",
                "risk_flags": [f"risk_{index}" for index in range(25)],
                "overfit_warnings": [f"warning_{index}" for index in range(25)],
                "paper_trading_readiness": "needs_review",
                "recommended_next_steps": [f"research_step_{index}" for index in range(25)],
            }
        ),
        candidate_review_id=7,
        backtest_run_id=11,
    )

    assert parsed["review_status"] == "completed"
    assert len(parsed["risk_flags"]) == 20
    assert len(parsed["overfit_warnings"]) == 20
    assert len(parsed["recommended_next_steps"]) == 20
    assert parsed["risk_flags"][-1] == "risk_19"
    assert parsed["recommended_next_steps"][-1] == "research_step_19"


def test_load_backtest_review_context_reads_review_source_run_backtest_and_metrics():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    now = datetime(2026, 6, 24, 9, 0, 0)

    with session_scope(engine) as session:
        source = AgentRunRepository(session).create_running(
            agent_type="strategy_idea",
            symbol="000001",
            model_name="fake-llm",
            request_payload=json.dumps({"idea": "ma cross"}),
            job_run_id=None,
            started_at=now,
        )
        AgentRunRepository(session).mark_succeeded(
            source,
            metrics_payload=json.dumps({"tokens": 123}),
            result_payload=json.dumps(
                {
                    "parsed": True,
                    "candidate_payload": {"strategy_name": "ma_cross", "symbol": "000001"},
                }
            ),
            finished_at=now,
            duration_ms=1,
        )
        run = BacktestRunORM(
            strategy_name="ma_cross",
            symbol="000001",
            initial_cash=Decimal("100000.000000"),
            final_equity=Decimal("95000.000000"),
            status="done",
            created_at=now,
        )
        session.add(run)
        session.flush()
        session.add_all(
            [
                BacktestEquityPointORM(
                    run_id=run.id,
                    timestamp=date(2026, 1, 1),
                    equity=Decimal("100000.000000"),
                    cash=Decimal("100000.000000"),
                    market_value=Decimal("0.000000"),
                    drawdown=Decimal("0.000000"),
                ),
                BacktestEquityPointORM(
                    run_id=run.id,
                    timestamp=date(2026, 1, 2),
                    equity=Decimal("95000.000000"),
                    cash=Decimal("95000.000000"),
                    market_value=Decimal("0.000000"),
                    drawdown=Decimal("0.050000"),
                ),
            ]
        )
        session.add(
            BacktestOrderORM(
                run_id=run.id,
                instrument_id=1,
                symbol="000001",
                side="buy",
                quantity=100,
                reason="ma_cross",
                status="filled",
                submitted_at=date(2026, 1, 2),
            )
        )
        review = AgentCandidateReviewRepository(session).create_decision(
            source_agent_run_id=source.id,
            status="backtest_succeeded",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload=json.dumps({"strategy_name": "ma_cross", "symbol": "000001"}),
            backtest_request_payload=json.dumps(
                {"job_type": "backtest_ma_cross", "payload": {"symbol": "000001"}}
            ),
            operator="local",
            operator_note="approved for research backtest",
            decided_at=now,
            created_at=now,
        )
        review.backtest_run_id = run.id
        review_id = review.id
        run_id = run.id

    context = load_backtest_review_context(engine, review_id)

    assert context["candidate_review"]["id"] == review_id
    assert context["candidate_review"]["backtest_run_id"] == run_id
    assert context["source_agent_run"]["id"] == 1
    assert context["source_agent_result"]["candidate_payload"]["strategy_name"] == "ma_cross"
    assert context["backtest_run"]["id"] == run_id
    assert context["metrics"] == {
        "initial_cash": "100000.000000",
        "final_equity": "95000.000000",
        "absolute_pnl": "-5000.000000",
        "return_pct": "-5.000000",
        "status": "done",
        "symbol": "000001",
        "strategy_name": "ma_cross",
        "equity_point_count": 2,
        "max_drawdown": "0.050000",
        "order_count": 1,
    }
