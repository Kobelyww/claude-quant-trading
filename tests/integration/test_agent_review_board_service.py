from datetime import date, datetime
import json

from quant_trading.agents import review_board
from quant_trading.agents.review_board import ReviewBoardService
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    BacktestRunORM,
    DataQualityReportORM,
    ResearchValidationReportORM,
)
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentReviewBoardRunRepository,
    AgentReviewBoardVoteRepository,
    AgentRunRepository,
    SafetyIncidentRepository,
    StrategySkillRepository,
)


def test_review_board_service_persists_deterministic_votes_for_candidate_review():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id = seed_candidate_review_with_validation_report(
        engine,
        validation_status="needs_review",
        readiness_floor="not_ready",
        data_quality_status="passed",
    )

    result = ReviewBoardService(engine).run_for_candidate_review(candidate_review_id)

    assert result.final_recommendation == "needs_more_research"
    with session_scope(engine) as session:
        board_runs = AgentReviewBoardRunRepository(session).list_recent(limit=10)
        assert len(board_runs) == 1
        votes = AgentReviewBoardVoteRepository(session).list_for_board(board_runs[0].id)
        assert {vote.reviewer_role for vote in votes} == {
            "data_steward",
            "strategy_researcher",
            "risk_officer",
            "validation_reviewer",
            "operations_reviewer",
        }


def test_review_board_operations_reviewer_flags_linked_unresolved_safety_incident():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id = seed_candidate_review_with_validation_report(
        engine,
        validation_status="passed",
        readiness_floor="ready_for_paper_research",
        data_quality_status="passed",
    )
    with session_scope(engine) as session:
        SafetyIncidentRepository(session).create(
            severity="high",
            category="pre_live_safety",
            resource_type="agent_candidate_review",
            resource_id=candidate_review_id,
            reason_code="pre_live_safety_unresolved",
            message="manual safety review still open",
            payload={"candidate_review_id": candidate_review_id},
            created_at=datetime(2026, 7, 6, 9, 5, 0),
        )

    ReviewBoardService(engine).run_for_candidate_review(candidate_review_id)

    with session_scope(engine) as session:
        board_runs = AgentReviewBoardRunRepository(session).list_recent(limit=10)
        votes = AgentReviewBoardVoteRepository(session).list_for_board(board_runs[0].id)
        operations_vote = next(
            vote for vote in votes if vote.reviewer_role == "operations_reviewer"
        )
        assert operations_vote.vote != "pass"
        assert operations_vote.reason_code == "unresolved_linked_safety_incident"


def test_review_board_persists_vote_for_non_object_candidate_payload():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id = seed_candidate_review_with_validation_report(
        engine,
        validation_status="passed",
        readiness_floor="ready_for_paper_research",
        data_quality_status="passed",
        candidate_payload="[]",
    )

    result = ReviewBoardService(engine).run_for_candidate_review(candidate_review_id)

    assert result.final_recommendation == "needs_more_research"
    with session_scope(engine) as session:
        board_runs = AgentReviewBoardRunRepository(session).list_recent(limit=10)
        assert len(board_runs) == 1
        votes = AgentReviewBoardVoteRepository(session).list_for_board(board_runs[0].id)
        strategy_vote = next(
            vote for vote in votes if vote.reviewer_role == "strategy_researcher"
        )
        assert strategy_vote.vote == "needs_review"
        assert strategy_vote.reason_code == "strategy_payload_invalid"


def test_review_board_validation_reviewer_caps_running_validation():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id = seed_candidate_review_with_validation_report(
        engine,
        validation_status="running",
        readiness_floor="running",
        data_quality_status="passed",
    )

    result = ReviewBoardService(engine).run_for_candidate_review(candidate_review_id)

    assert result.final_recommendation == "needs_more_research"
    with session_scope(engine) as session:
        board_runs = AgentReviewBoardRunRepository(session).list_recent(limit=10)
        votes = AgentReviewBoardVoteRepository(session).list_for_board(board_runs[0].id)
        validation_vote = next(
            vote for vote in votes if vote.reviewer_role == "validation_reviewer"
        )
        assert validation_vote.vote == "needs_review"
        assert validation_vote.reason_code == "validation_unknown_or_in_progress"


def test_review_board_service_redacts_settings_secret_in_failed_run_summary(monkeypatch):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    secret = "configured-token-456"
    candidate_review_id = seed_candidate_review_with_validation_report(
        engine,
        validation_status="needs_review",
        readiness_floor="not_ready",
        data_quality_status="passed",
    )

    def fail_votes(**_: object) -> None:
        raise RuntimeError(f"reviewer failed with {secret}")

    monkeypatch.setattr(review_board, "_deterministic_votes", fail_votes)

    try:
        ReviewBoardService(
            engine,
            settings=AppSettings(api_token=secret),
        ).run_for_candidate_review(candidate_review_id)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected review board failure")

    with session_scope(engine) as session:
        board_run = AgentReviewBoardRunRepository(session).list_recent(limit=1)[0]
        summary = json.loads(board_run.summary_payload)
        assert board_run.status == "failed"
        assert secret not in summary["error_message"]
        assert "[REDACTED]" in summary["error_message"]


def seed_candidate_review_with_validation_report(
    engine,
    *,
    validation_status: str,
    readiness_floor: str,
    data_quality_status: str,
    candidate_payload: str | None = None,
) -> int:
    now = datetime(2026, 7, 6, 9, 0, 0)
    if candidate_payload is None:
        candidate_payload = json.dumps(
            {
                "strategy_name": "ma_cross",
                "strategy_skill_key": "ma_cross",
                "strategy_skill_version": "1.0.0",
                "symbol": "000001",
            },
            sort_keys=True,
        )
    with session_scope(engine) as session:
        StrategySkillRepository(session).ensure_seeded(now)
        source = AgentRunRepository(session).create_running(
            agent_type="strategy_idea",
            symbol="000001",
            model_name="fake-llm",
            request_payload=json.dumps({"symbol": "000001"}),
            job_run_id=None,
            started_at=now,
        )
        AgentRunRepository(session).mark_succeeded(
            source,
            metrics_payload="{}",
            result_payload=json.dumps(
                {
                    "candidate_payload": {
                        "strategy_name": "ma_cross",
                        "strategy_skill_key": "ma_cross",
                        "strategy_skill_version": "1.0.0",
                        "symbol": "000001",
                    },
                },
                sort_keys=True,
            ),
            finished_at=now,
            duration_ms=1,
        )
        candidate = AgentCandidateReviewRepository(session).create_decision(
            source_agent_run_id=source.id,
            status="backtest_succeeded",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload=candidate_payload,
            backtest_request_payload=json.dumps(
                {"job_type": "backtest_ma_cross", "payload": {"symbol": "000001"}},
                sort_keys=True,
            ),
            operator="tester",
            operator_note="approved for validation",
            decided_at=now,
            created_at=now,
        )
        backtest = BacktestRunORM(
            strategy_name="ma_cross",
            symbol="000001",
            initial_cash=100000,
            final_equity=101000,
            status="succeeded",
            created_at=now,
        )
        session.add(backtest)
        session.flush()
        data_quality = DataQualityReportORM(
            candidate_review_id=candidate.id,
            backtest_run_id=backtest.id,
            symbol="000001",
            source="test",
            adjusted="qfq",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            bar_count=2,
            expected_bar_count=2,
            missing_bar_count=0,
            duplicate_timestamp_count=0,
            non_positive_price_count=0,
            non_positive_volume_count=0,
            invalid_ohlc_count=0,
            stale_data=False,
            data_fingerprint="test-fingerprint",
            status=data_quality_status,
            severity="none" if data_quality_status == "passed" else "high",
            findings_payload="{}",
            created_at=now,
            finished_at=now,
            duration_ms=1,
        )
        session.add(data_quality)
        session.flush()
        validation = ResearchValidationReportORM(
            candidate_review_id=candidate.id,
            source_backtest_run_id=backtest.id,
            data_quality_report_id=data_quality.id,
            symbol="000001",
            strategy_name="ma_cross",
            validation_status=validation_status,
            readiness_floor=readiness_floor,
            in_sample_metrics_payload="{}",
            out_of_sample_metrics_payload="{}",
            walk_forward_payload="{}",
            parameter_sensitivity_payload="{}",
            benchmark_payload="{}",
            summary_payload=json.dumps({"reasons": []}, sort_keys=True),
            created_at=now,
            finished_at=now,
            duration_ms=1,
        )
        session.add(validation)
        session.flush()
        candidate.backtest_run_id = backtest.id
        candidate.data_quality_report_id = data_quality.id
        candidate.research_validation_report_id = validation.id
        candidate.updated_at = now
        return candidate.id
