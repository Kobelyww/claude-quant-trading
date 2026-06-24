import json
from datetime import datetime

import pytest
from sqlalchemy import select

from quant_trading.agents.candidates import BACKTEST_MA_CROSS
from quant_trading.agents.models import AGENT_MARKET_ANALYSIS, AGENT_STRATEGY_IDEA
from quant_trading.agents.candidate_reviews import (
    CandidateReviewConflictError,
    CandidateReviewValidationError,
    approve_strategy_candidate,
    reject_strategy_candidate,
)
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    AgentRunORM,
    BacktestRunORM,
    BrokerOrderEventORM,
    JobRunORM,
    PaperRunORM,
)
from quant_trading.storage.repositories import AgentRunRepository


def _settings() -> AppSettings:
    return AppSettings(job_executor="inline")


def _create_engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def _candidate_result(
    *,
    parsed=True,
    validation_status="passed",
    requires_human_approval=True,
    candidate_payload=None,
    backtest_request_payload=None,
):
    candidate = (
        {
            "strategy_name": "ma_cross",
            "symbol": "000001",
            "parameters": {
                "short_window": 5,
                "long_window": 20,
                "order_size": 100,
            },
            "requires_human_approval": requires_human_approval,
        }
        if candidate_payload is None
        else candidate_payload
    )
    backtest_request = (
        {
            "job_type": BACKTEST_MA_CROSS,
            "payload": {
                "symbol": "000001",
                "short_window": 5,
                "long_window": 20,
                "order_size": 100,
                "initial_cash": "100000",
            },
        }
        if backtest_request_payload is None
        else backtest_request_payload
    )
    return {
        "parsed": parsed,
        "validation_status": validation_status,
        "candidate_payload": candidate,
        "backtest_request_payload": backtest_request,
        "requires_human_approval": requires_human_approval,
    }


def _create_source_agent_run(
    engine,
    *,
    agent_type=AGENT_STRATEGY_IDEA,
    status="succeeded",
    result_payload=None,
) -> int:
    with session_scope(engine) as session:
        repo = AgentRunRepository(session)
        row = repo.create_running(
            agent_type=agent_type,
            symbol="000001",
            model_name="fake-llm",
            request_payload="{}",
            job_run_id=None,
            started_at=datetime(2026, 6, 24, 9, 0, 0),
        )
        if status == "succeeded":
            repo.mark_succeeded(
                row,
                metrics_payload="{}",
                result_payload=json.dumps(
                    result_payload if result_payload is not None else _candidate_result(),
                    sort_keys=True,
                ),
                finished_at=datetime(2026, 6, 24, 9, 0, 1),
                duration_ms=1,
            )
        elif status == "failed":
            repo.mark_failed(
                row,
                "agent failed",
                finished_at=datetime(2026, 6, 24, 9, 0, 1),
                duration_ms=1,
            )
        else:
            row.status = status
            session.flush()
        return row.id


def _counts(engine):
    with session_scope(engine) as session:
        return {
            "reviews": len(session.scalars(select(AgentCandidateReviewORM)).all()),
            "jobs": len(session.scalars(select(JobRunORM)).all()),
            "backtests": len(session.scalars(select(BacktestRunORM)).all()),
            "papers": len(session.scalars(select(PaperRunORM)).all()),
            "broker_events": len(session.scalars(select(BrokerOrderEventORM)).all()),
        }


def test_approving_valid_strategy_candidate_submits_backtest_and_links_inline_result(
    legacy_sqlite_db,
):
    engine = _create_engine()
    import_legacy_sqlite(legacy_sqlite_db, engine)
    source_id = _create_source_agent_run(engine)

    review = approve_strategy_candidate(
        engine,
        source_id,
        operator="research lead",
        note="approved for deterministic backtest",
        settings=_settings(),
    )

    assert review.status == "backtest_succeeded"
    assert review.backtest_job_run_id is not None
    assert review.backtest_run_id is not None
    assert review.operator == "research lead"
    assert json.loads(review.candidate_payload) == _candidate_result()["candidate_payload"]
    assert json.loads(review.backtest_request_payload) == _candidate_result()[
        "backtest_request_payload"
    ]
    with session_scope(engine) as session:
        job = session.get(JobRunORM, review.backtest_job_run_id)
        assert job is not None
        assert job.job_type == BACKTEST_MA_CROSS
        assert job.status == "succeeded"
        assert json.loads(job.request_payload) == _candidate_result()[
            "backtest_request_payload"
        ]["payload"]
        assert json.loads(job.result_payload)["run_id"] == review.backtest_run_id


def test_approving_with_missing_market_data_records_backtest_failure():
    engine = _create_engine()
    source_id = _create_source_agent_run(engine)

    review = approve_strategy_candidate(
        engine,
        source_id,
        operator="research lead",
        note="try anyway",
        settings=_settings(),
    )

    assert review.status == "backtest_failed"
    assert review.backtest_job_run_id is not None
    assert review.backtest_run_id is None
    assert review.error_message is not None
    assert "no market bars found" in review.error_message
    assert len(review.error_message) <= 1000
    with session_scope(engine) as session:
        job = session.get(JobRunORM, review.backtest_job_run_id)
        assert job is not None
        assert job.status == "failed"


def test_duplicate_approval_conflicts_and_submits_no_second_job(legacy_sqlite_db):
    engine = _create_engine()
    import_legacy_sqlite(legacy_sqlite_db, engine)
    source_id = _create_source_agent_run(engine)
    approve_strategy_candidate(
        engine,
        source_id,
        operator="research lead",
        note="approved",
        settings=_settings(),
    )

    with pytest.raises(CandidateReviewConflictError, match="candidate already submitted"):
        approve_strategy_candidate(
            engine,
            source_id,
            operator="research lead",
            note="again",
            settings=_settings(),
        )

    assert _counts(engine)["jobs"] == 1


def test_rejection_creates_rejected_review_and_no_execution_rows():
    engine = _create_engine()
    source_id = _create_source_agent_run(engine)

    review = reject_strategy_candidate(
        engine,
        source_id,
        operator="reviewer",
        note="not enough rationale",
    )

    assert review.status == "rejected"
    assert review.backtest_job_run_id is None
    assert review.backtest_run_id is None
    counts = _counts(engine)
    assert counts["reviews"] == 1
    assert counts["jobs"] == 0
    assert counts["backtests"] == 0
    assert counts["papers"] == 0
    assert counts["broker_events"] == 0


def test_rejecting_already_rejected_candidate_updates_same_review_row():
    engine = _create_engine()
    source_id = _create_source_agent_run(engine)
    first = reject_strategy_candidate(
        engine,
        source_id,
        operator="reviewer-a",
        note="first note",
    )

    second = reject_strategy_candidate(
        engine,
        source_id,
        operator="reviewer-b",
        note="updated note",
    )

    assert second.id == first.id
    assert second.status == "rejected"
    assert second.operator == "reviewer-b"
    assert second.operator_note == "updated note"
    assert _counts(engine)["jobs"] == 0


def test_rejecting_after_approval_conflicts():
    engine = _create_engine()
    source_id = _create_source_agent_run(engine)
    approve_strategy_candidate(
        engine,
        source_id,
        operator="research lead",
        note="approved",
        settings=_settings(),
    )

    with pytest.raises(
        CandidateReviewConflictError,
        match="cannot reject candidate after approval",
    ):
        reject_strategy_candidate(
            engine,
            source_id,
            operator="reviewer",
            note="late rejection",
        )

    assert _counts(engine)["reviews"] == 1


@pytest.mark.parametrize(
    ("agent_type", "status", "result_payload", "message"),
    [
        (
            AGENT_MARKET_ANALYSIS,
            "succeeded",
            _candidate_result(),
            "source agent run is not a strategy idea",
        ),
        (
            AGENT_STRATEGY_IDEA,
            "failed",
            _candidate_result(),
            "source agent run has not succeeded",
        ),
        (
            AGENT_STRATEGY_IDEA,
            "succeeded",
            _candidate_result(parsed=False),
            "strategy candidate was not parsed",
        ),
        (
            AGENT_STRATEGY_IDEA,
            "succeeded",
            _candidate_result(validation_status="failed"),
            "candidate validation did not pass",
        ),
        (
            AGENT_STRATEGY_IDEA,
            "succeeded",
            _candidate_result(
                backtest_request_payload={
                    "job_type": "paper_run",
                    "payload": {"symbol": "000001"},
                }
            ),
            "unsupported backtest job type",
        ),
    ],
)
def test_invalid_approval_source_cases_create_no_review_or_job(
    agent_type,
    status,
    result_payload,
    message,
):
    engine = _create_engine()
    source_id = _create_source_agent_run(
        engine,
        agent_type=agent_type,
        status=status,
        result_payload=result_payload,
    )

    with pytest.raises(CandidateReviewValidationError, match=message):
        approve_strategy_candidate(
            engine,
            source_id,
            operator="research lead",
            note="approve",
            settings=_settings(),
        )

    counts = _counts(engine)
    assert counts["reviews"] == 0
    assert counts["jobs"] == 0
