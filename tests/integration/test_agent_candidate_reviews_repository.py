import json
from datetime import datetime

from sqlalchemy import select

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    AgentRunORM,
    BacktestRunORM,
    JobRunORM,
)
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentRunRepository,
    DataQualityReportRepository,
)


def _create_source_agent_run(session):
    row = AgentRunRepository(session).create_running(
        agent_type="strategy_idea",
        symbol="000001",
        model_name="fake-llm",
        request_payload="{}",
        job_run_id=None,
        started_at=datetime(2026, 6, 24, 9, 0, 0),
    )
    AgentRunRepository(session).mark_succeeded(
        row,
        metrics_payload="{}",
        result_payload=json.dumps(
            {
                "parsed": True,
                "validation_status": "passed",
                "candidate_payload": {
                    "strategy_name": "ma_cross",
                    "symbol": "000001",
                    "parameters": {
                        "short_window": 5,
                        "long_window": 20,
                        "order_size": 100,
                    },
                    "requires_human_approval": True,
                },
                "backtest_request_payload": {
                    "job_type": "backtest_ma_cross",
                    "payload": {
                        "symbol": "000001",
                        "short_window": 5,
                        "long_window": 20,
                        "order_size": 100,
                        "initial_cash": "100000",
                    },
                },
                "requires_human_approval": True,
            },
            sort_keys=True,
        ),
        finished_at=datetime(2026, 6, 24, 9, 0, 1),
        duration_ms=1,
    )
    return row


def test_candidate_review_repository_lifecycle():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    now = datetime(2026, 6, 24, 9, 0, 0)

    with session_scope(engine) as session:
        source = _create_source_agent_run(session)
        backtest_job = JobRunORM(
            job_type="backtest_ma_cross",
            status="queued",
            progress=0,
            request_payload="{}",
            result_payload="{}",
            queued_at=now,
            created_at=now,
            updated_at=now,
        )
        backtest_run = BacktestRunORM(
            strategy_name="ma_cross",
            symbol="000001",
            initial_cash=100000,
            final_equity=101000,
            status="succeeded",
            created_at=now,
        )
        review_agent = AgentRunORM(
            agent_type="backtest_review",
            status="succeeded",
            symbol="000001",
            model_name="fake-llm",
            request_payload="{}",
            metrics_payload="{}",
            result_payload="{}",
            started_at=now,
            finished_at=now,
            duration_ms=1,
            created_at=now,
        )
        session.add_all([backtest_job, backtest_run, review_agent])
        session.flush()
        repo = AgentCandidateReviewRepository(session)
        review = repo.create_decision(
            source_agent_run_id=source.id,
            status="approved",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload=json.dumps({"strategy_name": "ma_cross"}, sort_keys=True),
            backtest_request_payload=json.dumps(
                {"job_type": "backtest_ma_cross", "payload": {"symbol": "000001"}},
                sort_keys=True,
            ),
            operator="local",
            operator_note="approved for research backtest",
            decided_at=now,
            created_at=now,
        )
        review_id = review.id
        repo.mark_backtest_submitted(
            review,
            backtest_job_run_id=backtest_job.id,
            updated_at=now,
        )
        repo.mark_backtest_succeeded(
            review,
            backtest_run_id=backtest_run.id,
            updated_at=now,
        )
        repo.mark_review_requested(
            review,
            review_agent_run_id=review_agent.id,
            updated_at=now,
        )
        repo.mark_review_succeeded(
            review,
            review_agent_run_id=review_agent.id,
            updated_at=now,
        )
        backtest_job_id = backtest_job.id
        backtest_run_id = backtest_run.id
        review_agent_id = review_agent.id

    with session_scope(engine) as session:
        review = AgentCandidateReviewRepository(session).get(review_id)
        assert review is not None
        assert review.source_agent_run_id == 1
        assert review.status == "review_succeeded"
        assert review.symbol == "000001"
        assert review.strategy_name == "ma_cross"
        assert review.operator == "local"
        assert review.operator_note == "approved for research backtest"
        assert review.backtest_job_run_id == backtest_job_id
        assert review.backtest_run_id == backtest_run_id
        assert review.review_agent_run_id == review_agent_id
        assert review.error_message is None
        assert AgentCandidateReviewRepository(session).get_by_source_agent_run_id(1).id == review_id
        assert [row.id for row in AgentCandidateReviewRepository(session).list_recent()] == [review_id]


def test_candidate_review_update_rejection_refreshes_payloads():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    now = datetime(2026, 6, 24, 9, 0, 0)

    with session_scope(engine) as session:
        source = _create_source_agent_run(session)
        repo = AgentCandidateReviewRepository(session)
        review = repo.create_decision(
            source_agent_run_id=source.id,
            status="pending",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload='{"old": true}',
            backtest_request_payload='{"old_backtest": true}',
            operator="",
            operator_note="",
            decided_at=None,
            created_at=now,
        )
        review_id = review.id
        repo.update_rejection(
            review,
            candidate_payload='{"new": true}',
            backtest_request_payload='{"new_backtest": true}',
            operator="local",
            operator_note="reject after edits",
            decided_at=now,
            updated_at=now,
        )

    with session_scope(engine) as session:
        review = AgentCandidateReviewRepository(session).get(review_id)
        assert review is not None
        assert review.status == "rejected"
        assert review.candidate_payload == '{"new": true}'
        assert review.backtest_request_payload == '{"new_backtest": true}'
        assert review.operator == "local"
        assert review.operator_note == "reject after edits"


def test_candidate_review_source_agent_run_is_unique():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    now = datetime(2026, 6, 24, 9, 0, 0)

    with session_scope(engine) as session:
        source = _create_source_agent_run(session)
        source_id = source.id
        repo = AgentCandidateReviewRepository(session)
        repo.create_decision(
            source_agent_run_id=source_id,
            status="rejected",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload="{}",
            backtest_request_payload="{}",
            operator="local",
            operator_note="insufficient thesis",
            decided_at=now,
            created_at=now,
        )

    with session_scope(engine) as session:
        repo = AgentCandidateReviewRepository(session)
        try:
            repo.create_decision(
                source_agent_run_id=source_id,
                status="approved",
                symbol="000001",
                strategy_name="ma_cross",
                candidate_payload="{}",
                backtest_request_payload="{}",
                operator="local",
                operator_note="duplicate",
                decided_at=now,
                created_at=now,
            )
        except Exception as exc:
            session.rollback()
            assert "UNIQUE" in str(exc).upper() or "unique" in exc.__class__.__name__.lower()
        else:
            raise AssertionError("duplicate candidate review should violate unique source")

    with session_scope(engine) as session:
        rows = session.scalars(select(AgentCandidateReviewORM)).all()
        assert len(rows) == 1
        assert session.get(AgentRunORM, 1) is not None


def test_candidate_review_repository_links_data_quality_report():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    created_at = datetime(2026, 6, 24, 9, 0, 0)
    linked_at = datetime(2026, 6, 24, 9, 1, 0)

    with session_scope(engine) as session:
        source = _create_source_agent_run(session)
        review_repo = AgentCandidateReviewRepository(session)
        review = review_repo.create_decision(
            source_agent_run_id=source.id,
            status="approved",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload="{}",
            backtest_request_payload="{}",
            operator="local",
            operator_note="approved",
            decided_at=created_at,
            created_at=created_at,
        )
        report = DataQualityReportRepository(session).create_running(
            candidate_review_id=review.id,
            backtest_run_id=None,
            job_run_id=None,
            symbol="000001",
            source="akshare",
            adjusted="qfq",
            start_date=None,
            end_date=None,
            created_at=created_at,
        )
        review_repo.link_data_quality_report(
            review,
            data_quality_report_id=report.id,
            updated_at=linked_at,
        )
        review_id = review.id
        report_id = report.id

    with session_scope(engine) as session:
        review = AgentCandidateReviewRepository(session).get(review_id)
        assert review is not None
        assert review.data_quality_report_id == report_id
        assert review.updated_at == linked_at
