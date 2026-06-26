import json
from datetime import datetime

from sqlalchemy import func, select

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    BacktestRunORM,
    JobRunORM,
    ResearchValidationReportORM,
)
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentRunRepository,
    ResearchValidationReportRepository,
)


def _seed_candidate_review(session) -> tuple[int, int]:
    now = datetime(2026, 6, 26, 9, 0, 0)
    source = AgentRunRepository(session).create_running(
        agent_type="strategy_idea",
        symbol="000001",
        model_name="fake-llm",
        request_payload="{}",
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
                    "symbol": "000001",
                }
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
        candidate_payload=json.dumps({"strategy_name": "ma_cross"}, sort_keys=True),
        backtest_request_payload=json.dumps(
            {"job_type": "backtest_ma_cross", "payload": {"symbol": "000001"}},
            sort_keys=True,
        ),
        operator="local",
        operator_note="approved",
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
    return candidate.id, backtest.id


def test_research_validation_report_repository_create_update_and_filters():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    started = datetime(2026, 6, 26, 9, 0, 0)
    finished = datetime(2026, 6, 26, 9, 0, 1)

    with session_scope(engine) as session:
        candidate_review_id, source_backtest_run_id = _seed_candidate_review(session)
        repo = ResearchValidationReportRepository(session)
        row = repo.create_or_reset_running(
            candidate_review_id=candidate_review_id,
            source_backtest_run_id=source_backtest_run_id,
            data_quality_report_id=None,
            job_run_id=None,
            symbol="000001",
            strategy_name="ma_cross",
            started_at=started,
        )
        repo.mark_completed(
            row,
            validation_status="passed",
            readiness_floor="ready_for_paper_research",
            data_quality_report_id=None,
            in_sample_metrics_payload='{"sharpe":1.2}',
            out_of_sample_metrics_payload='{"sharpe":1.1}',
            walk_forward_payload='{"windows":3}',
            parameter_sensitivity_payload='{"stable":true}',
            benchmark_payload='{"excess_return":0.03}',
            summary_payload='{"research_only":true}',
            finished_at=finished,
            duration_ms=1000,
        )
        row_id = row.id
        candidate_id = candidate_review_id

    with session_scope(engine) as session:
        repo = ResearchValidationReportRepository(session)
        row = repo.get(row_id)
        assert row is not None
        assert row.validation_status == "passed"
        assert row.readiness_floor == "ready_for_paper_research"
        assert repo.get_by_candidate_review_id(candidate_id).id == row.id
        assert [item.id for item in repo.list_recent(candidate_review_id=candidate_id)] == [
            row.id
        ]
        assert [item.id for item in repo.list_recent(validation_status="passed")] == [
            row.id
        ]


def test_research_validation_report_repository_reuses_candidate_row():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    first_started = datetime(2026, 6, 26, 9, 0, 0)
    second_started = datetime(2026, 6, 26, 10, 0, 0)

    with session_scope(engine) as session:
        candidate_review_id, source_backtest_run_id = _seed_candidate_review(session)
        first_job = JobRunORM(
            job_type="research_validation",
            status="running",
            progress=10,
            request_payload="{}",
            result_payload="{}",
            queued_at=first_started,
            started_at=first_started,
            created_at=first_started,
            updated_at=first_started,
        )
        second_job = JobRunORM(
            job_type="research_validation",
            status="running",
            progress=10,
            request_payload="{}",
            result_payload="{}",
            queued_at=second_started,
            started_at=second_started,
            created_at=second_started,
            updated_at=second_started,
        )
        session.add_all([first_job, second_job])
        session.flush()
        repo = ResearchValidationReportRepository(session)
        row = repo.create_or_reset_running(
            candidate_review_id=candidate_review_id,
            source_backtest_run_id=source_backtest_run_id,
            data_quality_report_id=None,
            job_run_id=first_job.id,
            symbol="000001",
            strategy_name="ma_cross",
            started_at=first_started,
        )
        repo.mark_failed(
            row,
            "stale validation",
            finished_at=datetime(2026, 6, 26, 9, 0, 1),
            duration_ms=1000,
        )
        updated = repo.create_or_reset_running(
            candidate_review_id=candidate_review_id,
            source_backtest_run_id=source_backtest_run_id,
            data_quality_report_id=None,
            job_run_id=second_job.id,
            symbol="000001",
            strategy_name="ma_cross",
            started_at=second_started,
        )
        assert updated.id == row.id
        assert updated.validation_status == "running"
        assert updated.readiness_floor == "not_ready"
        assert updated.error_message is None
        assert updated.job_run_id == second_job.id
        assert updated.in_sample_metrics_payload == "{}"
        assert session.scalar(select(func.count(ResearchValidationReportORM.id))) == 1
        AgentCandidateReviewRepository(session).link_research_validation_report(
            session.get(AgentCandidateReviewORM, candidate_review_id),
            research_validation_report_id=updated.id,
            updated_at=second_started,
        )
        candidate = session.get(AgentCandidateReviewORM, candidate_review_id)
        assert candidate.research_validation_report_id == updated.id


def test_research_validation_report_repository_marks_failed_with_capped_error():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    started = datetime(2026, 6, 26, 9, 0, 0)
    finished = datetime(2026, 6, 26, 9, 0, 1)

    with session_scope(engine) as session:
        candidate_review_id, source_backtest_run_id = _seed_candidate_review(session)
        repo = ResearchValidationReportRepository(session)
        row = repo.create_or_reset_running(
            candidate_review_id=candidate_review_id,
            source_backtest_run_id=source_backtest_run_id,
            data_quality_report_id=None,
            job_run_id=None,
            symbol="000001",
            strategy_name="ma_cross",
            started_at=started,
        )
        repo.mark_failed(row, "x" * 1200, finished_at=finished, duration_ms=1000)
        row_id = row.id

    with session_scope(engine) as session:
        row = ResearchValidationReportRepository(session).get(row_id)
        assert row is not None
        assert row.validation_status == "failed"
        assert row.readiness_floor == "not_ready"
        assert row.duration_ms == 1000
        assert len(row.error_message) == 1000
