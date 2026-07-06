from datetime import date, datetime
from decimal import Decimal
import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from quant_trading.agents.memory import LearningMemoryService
from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    BacktestRunORM,
    BrokerOrderEventORM,
    DataQualityReportORM,
    PaperRunORM,
    ResearchValidationReportORM,
)
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentRunRepository,
    StrategySkillRepository,
)


def make_client(
    *,
    require_auth: bool = False,
    token: str = "local-token",
) -> tuple[TestClient, object]:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    settings = AppSettings(
        require_auth=require_auth,
        api_token=token if require_auth else None,
    )
    return TestClient(create_app(engine=engine, settings=settings)), engine


def test_agent_intelligence_lists_seeded_skills():
    client, _ = make_client()

    response = client.get("/agents/skills")

    assert response.status_code == 200
    assert response.json()[0]["skill_key"] == "ma_cross"
    assert response.json()[0]["version"] == "1.0.0"


def test_agent_intelligence_gets_seeded_skill_by_key():
    client, _ = make_client()

    response = client.get("/agents/skills/ma_cross")

    assert response.status_code == 200
    assert response.json()["skill_key"] == "ma_cross"
    assert response.json()["status"] == "active"


def test_extract_candidate_memories_command_requires_auth_when_enabled():
    client, _ = make_client(require_auth=True, token="secret")

    response = client.post("/agents/candidate-reviews/1/extract-memories")

    assert response.status_code == 401


def test_agent_intelligence_lists_and_retires_memories():
    client, engine = make_client()
    memory = LearningMemoryService(engine).create_manual_memory(
        memory_type="operator_decision",
        scope="symbol",
        title="Rejected noisy crossover",
        content="Rejected after deterministic validation gaps.",
        reason_code="candidate_rejected",
        operator="tester",
        symbol="000001",
        source_type="candidate_review",
        source_id=7,
    )

    list_response = client.get("/agents/memories?symbol=000001&limit=50")

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == memory.id
    assert list_response.json()[0]["symbol"] == "000001"

    retire_response = client.post(
        f"/agents/memories/{memory.id}/retire",
        json={"operator": "tester", "reason": "superseded"},
    )

    assert retire_response.status_code == 200
    assert retire_response.json()["id"] == memory.id
    assert retire_response.json()["status"] == "retired"
    assert retire_response.json()["retired_by"] == "tester"


def test_review_board_command_does_not_create_paper_or_broker_rows():
    client, engine = make_client()
    candidate_review_id = seed_candidate_review_with_validation_report(engine)

    response = client.post(
        f"/agents/candidate-reviews/{candidate_review_id}/review-board"
    )

    assert response.status_code == 200
    assert response.json()["final_recommendation"] in {
        "reject",
        "needs_more_research",
        "ready_for_human_backtest_approval",
        "ready_for_paper_research_consideration",
    }
    with session_scope(engine) as session:
        assert session.scalar(select(func.count(PaperRunORM.id))) == 0
        assert session.scalar(select(func.count(BrokerOrderEventORM.id))) == 0


def test_agent_intelligence_lists_review_board_run_with_votes():
    client, engine = make_client()
    candidate_review_id = seed_candidate_review_with_validation_report(engine)
    run_response = client.post(
        f"/agents/candidate-reviews/{candidate_review_id}/review-board"
    )
    run_id = run_response.json()["id"]

    list_response = client.get("/agents/review-board-runs?limit=50")
    detail_response = client.get(f"/agents/review-board-runs/{run_id}")

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == run_id
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == run_id
    assert {vote["reviewer_role"] for vote in detail_response.json()["votes"]} == {
        "data_steward",
        "strategy_researcher",
        "risk_officer",
        "validation_reviewer",
        "operations_reviewer",
    }


def seed_candidate_review_with_validation_report(engine) -> int:
    now = datetime(2026, 7, 6, 9, 0, 0)
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
            candidate_payload=json.dumps(
                {
                    "strategy_name": "ma_cross",
                    "strategy_skill_key": "ma_cross",
                    "strategy_skill_version": "1.0.0",
                    "symbol": "000001",
                },
                sort_keys=True,
            ),
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
            initial_cash=Decimal("100000"),
            final_equity=Decimal("101000"),
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
            status="passed",
            severity="none",
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
            validation_status="needs_review",
            readiness_floor="not_ready",
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
