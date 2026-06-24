from datetime import datetime
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from quant_trading.agents.candidates import BACKTEST_MA_CROSS
from quant_trading.agents.candidate_reviews import approve_strategy_candidate
from quant_trading.agents.models import AGENT_STRATEGY_IDEA
from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import (
    BacktestRunORM,
    BrokerOrderEventORM,
    JobRunORM,
    PaperRunORM,
)
from quant_trading.storage.repositories import AgentRunRepository


def _settings() -> AppSettings:
    return AppSettings(job_executor="inline")


def _rq_settings() -> AppSettings:
    return AppSettings(job_executor="rq", redis_url="redis://example.invalid:6379/0")


def _create_engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def _client(engine, settings: AppSettings | None = None) -> TestClient:
    return TestClient(create_app(engine=engine, settings=settings or _settings()))


def _candidate_result():
    return {
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
            "job_type": BACKTEST_MA_CROSS,
            "payload": {
                "symbol": "000001",
                "short_window": 5,
                "long_window": 20,
                "order_size": 100,
                "initial_cash": "100000",
            },
        },
        "requires_human_approval": True,
    }


def _create_source_agent_run(engine) -> int:
    with session_scope(engine) as session:
        repo = AgentRunRepository(session)
        row = repo.create_running(
            agent_type=AGENT_STRATEGY_IDEA,
            symbol="000001",
            model_name="fake-llm",
            request_payload="{}",
            job_run_id=None,
            started_at=datetime(2026, 6, 24, 9, 0, 0),
        )
        repo.mark_succeeded(
            row,
            metrics_payload="{}",
            result_payload=json.dumps(_candidate_result(), sort_keys=True),
            finished_at=datetime(2026, 6, 24, 9, 0, 1),
            duration_ms=1,
        )
        return row.id


def _create_source_agent_run_with_result(engine, result_payload: dict) -> int:
    with session_scope(engine) as session:
        repo = AgentRunRepository(session)
        row = repo.create_running(
            agent_type=AGENT_STRATEGY_IDEA,
            symbol="000001",
            model_name="fake-llm",
            request_payload="{}",
            job_run_id=None,
            started_at=datetime(2026, 6, 24, 9, 0, 0),
        )
        repo.mark_succeeded(
            row,
            metrics_payload="{}",
            result_payload=json.dumps(result_payload, sort_keys=True),
            finished_at=datetime(2026, 6, 24, 9, 0, 1),
            duration_ms=1,
        )
        return row.id


def _counts(engine):
    with session_scope(engine) as session:
        return {
            "jobs": len(session.scalars(select(JobRunORM)).all()),
            "backtests": len(session.scalars(select(BacktestRunORM)).all()),
            "papers": len(session.scalars(select(PaperRunORM)).all()),
            "broker_events": len(session.scalars(select(BrokerOrderEventORM)).all()),
        }


def test_approval_endpoint_submits_inline_backtest_and_list_get_return_decoded_payloads(
    legacy_sqlite_db,
):
    engine = _create_engine()
    import_legacy_sqlite(legacy_sqlite_db, engine)
    source_id = _create_source_agent_run(engine)
    client = _client(engine)

    approve_response = client.post(
        f"/agent-candidates/{source_id}/approve",
        json={"operator": "research lead", "note": "approved for deterministic backtest"},
    )
    list_response = client.get(
        "/agent-candidates",
        params={"status": "backtest_succeeded", "symbol": "000001", "limit": 10},
    )

    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["status"] == "backtest_succeeded"
    assert approved["source_agent_run_id"] == source_id
    assert approved["operator"] == "research lead"
    assert approved["candidate_payload"] == _candidate_result()["candidate_payload"]
    assert approved["backtest_request_payload"] == _candidate_result()[
        "backtest_request_payload"
    ]
    assert approved["backtest_job_run_id"] is not None
    assert approved["backtest_run_id"] is not None

    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [approved["id"]]
    assert list_response.json()[0]["candidate_payload"] == _candidate_result()[
        "candidate_payload"
    ]

    get_response = client.get(f"/agent-candidates/{approved['id']}")
    assert get_response.status_code == 200
    assert get_response.json() == approved

    counts = _counts(engine)
    assert counts["jobs"] == 1
    assert counts["backtests"] == 1
    assert counts["papers"] == 0
    assert counts["broker_events"] == 0


def test_reject_endpoint_creates_rejected_review_no_job_and_later_approval_conflicts():
    engine = _create_engine()
    source_id = _create_source_agent_run(engine)
    client = _client(engine)

    reject_response = client.post(
        f"/agent-candidates/{source_id}/reject",
        json={"operator": "reviewer", "note": "not enough rationale"},
    )
    approve_response = client.post(
        f"/agent-candidates/{source_id}/approve",
        json={"operator": "research lead", "note": "approve anyway"},
    )

    assert reject_response.status_code == 200
    rejected = reject_response.json()
    assert rejected["status"] == "rejected"
    assert rejected["backtest_job_run_id"] is None
    assert rejected["backtest_run_id"] is None
    assert rejected["candidate_payload"] == _candidate_result()["candidate_payload"]
    assert _counts(engine) == {
        "jobs": 0,
        "backtests": 0,
        "papers": 0,
        "broker_events": 0,
    }

    assert approve_response.status_code == 409
    assert approve_response.json()["detail"] == "candidate already rejected"


def test_refresh_backtest_endpoint_for_incomplete_queued_job_returns_conflict():
    class FakeRqJob:
        id = "queued-job"

    class CapturingQueue:
        def enqueue(self, func, *args):
            return FakeRqJob()

    engine = _create_engine()
    source_id = _create_source_agent_run(engine)
    review = approve_strategy_candidate(
        engine,
        source_id,
        operator="research lead",
        note="approved for async backtest",
        settings=_rq_settings(),
        queue_factory=lambda redis_url: CapturingQueue(),
    )
    client = _client(engine, settings=_rq_settings())
    assert review.status == "backtest_submitted"

    refresh_response = client.post(
        f"/agent-candidates/{review.id}/refresh-backtest",
    )

    assert refresh_response.status_code == 409
    assert refresh_response.json() == {
        "detail": "linked backtest job has not completed",
    }


def test_approval_endpoint_maps_candidate_validation_failure_to_conflict():
    engine = _create_engine()
    source_id = _create_source_agent_run_with_result(
        engine,
        {
            **_candidate_result(),
            "validation_status": "failed",
        },
    )
    client = _client(engine)

    response = client.post(
        f"/agent-candidates/{source_id}/approve",
        json={"operator": "research lead", "note": "approve"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "candidate validation did not pass"
    assert _counts(engine) == {
        "jobs": 0,
        "backtests": 0,
        "papers": 0,
        "broker_events": 0,
    }


def test_missing_and_malformed_candidate_decision_requests_return_expected_errors():
    engine = _create_engine()
    client = _client(engine)

    missing_get_response = client.get("/agent-candidates/999")
    approve_missing_response = client.post(
        "/agent-candidates/999/approve",
        json={"operator": "research lead", "note": "approve"},
    )
    blank_body_response = client.post(
        "/agent-candidates/999/reject",
        json={"operator": " ", "note": ""},
    )

    assert missing_get_response.status_code == 404
    assert missing_get_response.json()["detail"] == "candidate review not found"
    assert approve_missing_response.status_code == 404
    assert approve_missing_response.json()["detail"] == "source agent run not found"
    assert blank_body_response.status_code == 400
