from datetime import datetime
from decimal import Decimal
import json

import pytest

from quant_trading.agents.memory import (
    LearningMemoryError,
    LearningMemoryNotFoundError,
    LearningMemoryService,
)
from quant_trading.agents.output_safety import contains_unsafe_agent_text
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import BacktestRunORM, ResearchValidationReportORM
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentRunRepository,
    SafetyIncidentRepository,
)


@pytest.fixture
def in_memory_engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


@pytest.fixture
def rejected_candidate_review(in_memory_engine):
    now = datetime(2026, 7, 6, 9, 0, 0)
    with session_scope(in_memory_engine) as session:
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
                        "symbol": "000001",
                    },
                }
            ),
            finished_at=now,
            duration_ms=1,
        )
        return AgentCandidateReviewRepository(session).create_decision(
            source_agent_run_id=source.id,
            status="rejected",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload=json.dumps(
                {"strategy_name": "ma_cross", "symbol": "000001"}
            ),
            backtest_request_payload=json.dumps(
                {"job_type": "backtest_ma_cross", "payload": {"symbol": "000001"}}
            ),
            operator="tester",
            operator_note="insufficient validation evidence",
            decided_at=now,
            created_at=now,
        )


def test_shared_output_safety_rejects_live_order_and_code_text():
    assert contains_unsafe_agent_text(["place a live order tomorrow"]) is True
    assert contains_unsafe_agent_text(["```python\nprint('trade')\n```"]) is True
    assert contains_unsafe_agent_text(["research-only validation summary"]) is False


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "真实下单",
        "实盘交易",
        "保证收益",
        "稳赚",
    ],
)
def test_shared_output_safety_rejects_chinese_live_trading_and_profit_claims(
    unsafe_text,
):
    assert contains_unsafe_agent_text([unsafe_text]) is True


def test_memory_service_rejects_unsafe_memory_text(in_memory_engine):
    service = LearningMemoryService(in_memory_engine)
    with pytest.raises(LearningMemoryError, match="unsafe memory content"):
        service.create_manual_memory(
            memory_type="operator_decision",
            scope="global",
            title="bad",
            content="place a live order tomorrow",
            reason_code="unsafe",
            operator="tester",
        )


def test_memory_service_extracts_operator_rejection_memory(
    in_memory_engine,
    rejected_candidate_review,
):
    service = LearningMemoryService(in_memory_engine)
    results = service.extract_from_candidate_review(rejected_candidate_review.id)
    assert len(results) == 1
    assert results[0].memory_type == "operator_decision"
    assert results[0].reason_code == "candidate_rejected"

    duplicate_results = service.extract_from_candidate_review(rejected_candidate_review.id)
    assert duplicate_results[0].id == results[0].id


def test_memory_service_redacts_operator_note_secrets_before_persisting(
    in_memory_engine,
):
    now = datetime(2026, 7, 6, 9, 0, 0)
    with session_scope(in_memory_engine) as session:
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
                        "symbol": "000001",
                    },
                }
            ),
            finished_at=now,
            duration_ms=1,
        )
        review = AgentCandidateReviewRepository(session).create_decision(
            source_agent_run_id=source.id,
            status="rejected",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload=json.dumps(
                {"strategy_name": "ma_cross", "symbol": "000001"}
            ),
            backtest_request_payload=json.dumps(
                {"job_type": "backtest_ma_cross", "payload": {"symbol": "000001"}}
            ),
            operator="tester",
            operator_note="bad external note api key=sk-testsecret123456789",
            decided_at=now,
            created_at=now,
        )
        review_id = review.id

    service = LearningMemoryService(in_memory_engine)
    results = service.extract_from_candidate_review(review_id)
    retrieved = service.retrieve(symbol="000001")

    assert len(results) == 1
    assert "[REDACTED]" in results[0].content
    assert "sk-testsecret123456789" not in results[0].content
    assert "sk-testsecret123456789" not in retrieved[0].content


def test_memory_service_extracts_validation_report_failure_and_success(in_memory_engine):
    failed = _create_validation_report(
        in_memory_engine,
        validation_status="failed",
        readiness_floor="not_ready",
        summary_payload={"reasons": [{"code": "walk_forward_failed"}]},
        source_agent_run_id=101,
        candidate_source_id=201,
        backtest_id=301,
    )
    passed = _create_validation_report(
        in_memory_engine,
        validation_status="passed",
        readiness_floor="ready_for_paper_research",
        summary_payload={"reasons": []},
        source_agent_run_id=102,
        candidate_source_id=202,
        backtest_id=302,
    )
    service = LearningMemoryService(in_memory_engine)

    failed_results = service.extract_from_validation_report(failed.id)
    passed_results = service.extract_from_validation_report(passed.id)

    assert [(row.memory_type, row.reason_code) for row in failed_results] == [
        ("strategy_failure", "walk_forward_failed")
    ]
    assert failed_results[0].confidence == Decimal("0.9000")
    assert failed_results[0].importance == Decimal("0.7000")
    assert [(row.memory_type, row.reason_code) for row in passed_results] == [
        ("strategy_success", "research_validation_passed")
    ]
    assert passed_results[0].confidence == Decimal("0.7000")
    assert passed_results[0].importance == Decimal("0.5000")


def test_memory_service_ignores_running_validation_reports(in_memory_engine):
    running = _create_validation_report(
        in_memory_engine,
        validation_status="running",
        readiness_floor="needs_review",
        summary_payload={"reasons": [{"code": "still_running"}]},
        source_agent_run_id=103,
        candidate_source_id=203,
        backtest_id=303,
    )
    service = LearningMemoryService(in_memory_engine)

    assert service.extract_from_validation_report(running.id) == []


def test_memory_service_retrieves_by_scope_budget_and_retires(in_memory_engine):
    service = LearningMemoryService(in_memory_engine)
    global_memory = service.create_manual_memory(
        memory_type="strategy_failure",
        scope="global",
        title="global lesson",
        content="Global validation lesson.",
        reason_code="global_lesson",
        operator="tester",
        source_id=1,
        importance=Decimal("0.9"),
    )
    symbol_memory = service.create_manual_memory(
        memory_type="strategy_failure",
        scope="symbol",
        title="symbol lesson",
        content="Symbol validation lesson.",
        reason_code="symbol_lesson",
        operator="tester",
        source_id=2,
        symbol="000001",
        importance=Decimal("0.4"),
    )

    results = service.retrieve(symbol="000001", limit=2, max_chars=80)

    assert [row.id for row in results] == [symbol_memory.id, global_memory.id]
    assert sum(len(row.title) + len(row.content) for row in results) <= 80

    retired = service.retire(symbol_memory.id, operator="tester", reason="superseded")
    remaining = service.retrieve(symbol="000001", limit=8, max_chars=3000)

    assert retired.id == symbol_memory.id
    assert symbol_memory.id not in {row.id for row in remaining}
    with pytest.raises(LearningMemoryNotFoundError):
        service.retire(999999, operator="tester", reason="missing")


def test_memory_service_extracts_safety_incident_lesson(in_memory_engine):
    now = datetime(2026, 7, 6, 9, 0, 0)
    with session_scope(in_memory_engine) as session:
        incident = SafetyIncidentRepository(session).create(
            severity="warning",
            category="agent_output",
            resource_type="agent_run",
            resource_id=77,
            reason_code="unsafe_output_blocked",
            message="Unsafe generated output was blocked.",
            payload={"source": "unit"},
            created_at=now,
        )
        incident_id = incident.id

    results = LearningMemoryService(in_memory_engine).extract_from_safety_incident(
        incident_id
    )

    assert len(results) == 1
    assert results[0].memory_type == "safety_incident_lesson"
    assert results[0].reason_code == "unsafe_output_blocked"
    assert "blocked" in results[0].content


def _create_validation_report(
    engine,
    *,
    validation_status: str,
    readiness_floor: str,
    summary_payload: dict,
    source_agent_run_id: int,
    candidate_source_id: int,
    backtest_id: int,
):
    now = datetime(2026, 7, 6, 9, 0, 0)
    with session_scope(engine) as session:
        source = AgentRunRepository(session).create_running(
            agent_type="strategy_idea",
            symbol="000001",
            model_name="fake-llm",
            request_payload=json.dumps({"symbol": "000001"}),
            job_run_id=None,
            started_at=now,
        )
        source.id = source_agent_run_id
        AgentRunRepository(session).mark_succeeded(
            source,
            metrics_payload="{}",
            result_payload="{}",
            finished_at=now,
            duration_ms=1,
        )
        run = BacktestRunORM(
            id=backtest_id,
            strategy_name="ma_cross",
            symbol="000001",
            initial_cash=Decimal("100000.000000"),
            final_equity=Decimal("99000.000000"),
            status="done",
            created_at=now,
        )
        session.add(run)
        review = AgentCandidateReviewRepository(session).create_decision(
            source_agent_run_id=source.id,
            status="backtest_succeeded",
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload=json.dumps(
                {"strategy_name": "ma_cross", "symbol": "000001"}
            ),
            backtest_request_payload=json.dumps(
                {"job_type": "backtest_ma_cross", "payload": {"symbol": "000001"}}
            ),
            operator="tester",
            operator_note="approved for research backtest",
            decided_at=now,
            created_at=now,
        )
        review.id = candidate_source_id
        report = ResearchValidationReportORM(
            candidate_review_id=review.id,
            source_backtest_run_id=run.id,
            data_quality_report_id=None,
            symbol="000001",
            strategy_name="ma_cross",
            validation_status=validation_status,
            readiness_floor=readiness_floor,
            in_sample_metrics_payload="{}",
            out_of_sample_metrics_payload="{}",
            walk_forward_payload="{}",
            parameter_sensitivity_payload="{}",
            benchmark_payload="{}",
            summary_payload=json.dumps(summary_payload),
            created_at=now,
            finished_at=now,
            duration_ms=1,
        )
        session.add(report)
        session.flush()
        return report
