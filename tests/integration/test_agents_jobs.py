import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.agents.llm import FakeLLMClient
from quant_trading.agents.models import (
    BacktestReviewRequest,
    MarketAnalysisRequest,
    StrategyIdeaRequest,
)
from quant_trading.agents.service import (
    run_backtest_review_agent,
    run_market_analysis_agent,
    run_strategy_idea_agent,
)
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import (
    AgentRunORM,
    DataQualityReportORM,
    ResearchValidationReportORM,
)
from quant_trading.storage.repositories import AgentCandidateReviewRepository, AgentRunRepository


VALID_MA_CROSS_RESPONSE = json.dumps(
    {
        "strategy_template": "ma_cross",
        "thesis": "Trend continuation research with a moving-average crossover.",
        "market_regime_assumption": "Directional daily market with enough liquidity.",
        "entry_rules": [
            "Enter research long exposure when the short moving average crosses above the long moving average."
        ],
        "exit_rules": [
            "Exit research exposure when the short moving average crosses below the long moving average."
        ],
        "risk_controls": ["Fixed order size and drawdown review before paper trading."],
        "parameters_to_test": {
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
            "initial_cash": "100000",
        },
        "data_requirements": ["Daily OHLCV bars."],
        "failure_modes": ["Whipsaw in range-bound markets."],
        "backtest_readiness": "ready",
    },
    ensure_ascii=False,
)

VALID_BACKTEST_REVIEW_RESPONSE = json.dumps(
    {
        "summary": "Backtest had positive historical PnL with limited sample coverage.",
        "risk_flags": ["small_sample"],
        "overfit_warnings": ["single_symbol"],
        "paper_trading_readiness": "needs_review",
        "recommended_next_steps": ["run out-of-sample research diagnostics"],
    },
    ensure_ascii=False,
)


def test_run_market_analysis_agent_persists_success(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)

    result = run_market_analysis_agent(
        engine,
        MarketAnalysisRequest(symbol="000001", lookback_bars=60),
        llm_client=FakeLLMClient("市场研究报告"),
        job_run_id=3,
    )

    with session_scope(engine) as session:
        row = session.scalar(select(AgentRunORM).where(AgentRunORM.id == result["agent_run_id"]))

    assert row is not None
    assert row.status == "succeeded"
    assert row.agent_type == "market_analysis"
    assert row.symbol == "000001"
    assert row.job_run_id == 3
    assert result["research_only"] is True
    assert result["report"] == "市场研究报告"


def test_run_strategy_idea_agent_persists_success():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    result = run_strategy_idea_agent(
        engine,
        StrategyIdeaRequest(idea="Buy pullbacks in an uptrend", symbol="000001"),
        llm_client=FakeLLMClient(VALID_MA_CROSS_RESPONSE),
        job_run_id=4,
    )

    with session_scope(engine) as session:
        row = session.get(AgentRunORM, result["agent_run_id"])

    assert row is not None
    assert row.status == "succeeded"
    assert row.agent_type == "strategy_idea"
    assert row.symbol == "000001"
    assert result["research_only"] is True
    assert result["parsed"] is True
    assert result["validation_status"] == "passed"
    assert result["validation_errors"] == []
    assert result["safety_flags"] == []
    assert result["candidate_payload"] == {
        "strategy_name": "ma_cross",
        "symbol": "000001",
        "parameters": {
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
        },
        "requires_human_approval": True,
    }
    assert result["backtest_request_payload"] == {
        "job_type": "backtest_ma_cross",
        "payload": {
            "symbol": "000001",
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
            "initial_cash": "100000",
        },
    }
    assert result["requires_human_approval"] is True
    persisted_result = json.loads(row.result_payload)
    assert persisted_result["validation_status"] == result["validation_status"]
    assert persisted_result["candidate_payload"] == result["candidate_payload"]
    assert persisted_result["backtest_request_payload"] == result["backtest_request_payload"]


def test_run_strategy_idea_agent_marks_unparseable_text_needs_review():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    result = run_strategy_idea_agent(
        engine,
        StrategyIdeaRequest(idea="Trend following", symbol="000001"),
        llm_client=FakeLLMClient("plain narrative response"),
        job_run_id=5,
    )

    assert result["parsed"] is False
    assert result["validation_status"] == "needs_review"
    assert result["validation_errors"] == []
    assert result["safety_flags"] == []
    assert result["candidate_payload"] is None
    assert result["backtest_request_payload"] is None
    assert result["requires_human_approval"] is True

    with session_scope(engine) as session:
        row = session.get(AgentRunORM, result["agent_run_id"])

    assert row is not None
    assert row.status == "succeeded"
    persisted_result = json.loads(row.result_payload)
    assert persisted_result["validation_status"] == "needs_review"
    assert persisted_result["candidate_payload"] is None
    assert persisted_result["backtest_request_payload"] is None


def test_run_backtest_review_agent_persists_research_only_result():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id, backtest_run_id = _seed_backtest_review_candidate(engine)

    result = run_backtest_review_agent(
        engine,
        BacktestReviewRequest(
            candidate_review_id=candidate_review_id,
            backtest_run_id=backtest_run_id,
            require_validation_report=False,
        ),
        llm_client=FakeLLMClient(VALID_BACKTEST_REVIEW_RESPONSE),
        job_run_id=8,
    )

    with session_scope(engine) as session:
        row = session.get(AgentRunORM, result["agent_run_id"])
        review = AgentCandidateReviewRepository(session).get(candidate_review_id)

    assert row is not None
    assert row.status == "succeeded"
    assert row.agent_type == "backtest_review"
    assert row.symbol == "000001"
    assert row.job_run_id == 8
    assert json.loads(row.request_payload) == {
        "backtest_run_id": backtest_run_id,
        "candidate_review_id": candidate_review_id,
        "require_validation_report": False,
    }
    assert json.loads(row.metrics_payload)["return_pct"] == "2.000000"
    assert result["agent_type"] == "backtest_review"
    assert result["research_only"] is True
    assert "not investment advice" in result["disclaimer"]
    assert result["candidate_review_id"] == candidate_review_id
    assert result["backtest_run_id"] == backtest_run_id
    assert result["review_status"] == "completed"
    assert result["paper_trading_readiness"] == "needs_review"
    assert review is not None
    assert review.status == "review_succeeded"
    assert review.review_agent_run_id == result["agent_run_id"]
    assert review.error_message is None


def test_run_backtest_review_agent_rejects_missing_validation_report_without_agent_row():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id, _ = _seed_backtest_review_candidate(engine)

    with pytest.raises(ValueError, match="validation report is required"):
        run_backtest_review_agent(
            engine,
            BacktestReviewRequest(candidate_review_id=candidate_review_id),
            llm_client=FakeLLMClient(VALID_BACKTEST_REVIEW_RESPONSE),
        )

    with session_scope(engine) as session:
        assert (
            session.scalar(
                select(func.count(AgentRunORM.id)).where(
                    AgentRunORM.agent_type == "backtest_review"
                )
            )
            == 0
        )


def test_run_backtest_review_agent_allows_explicit_validation_override():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id, backtest_run_id = _seed_backtest_review_candidate(engine)

    result = run_backtest_review_agent(
        engine,
        BacktestReviewRequest(
            candidate_review_id=candidate_review_id,
            require_validation_report=False,
        ),
        llm_client=FakeLLMClient(VALID_BACKTEST_REVIEW_RESPONSE),
    )

    assert result["candidate_review_id"] == candidate_review_id
    assert result["backtest_run_id"] == backtest_run_id
    assert result["paper_trading_readiness"] == "needs_review"
    assert result["validation_report_id"] is None
    assert result["data_quality_report_id"] is None


def test_run_backtest_review_agent_caps_readiness_by_validation_floor():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id, _ = _seed_backtest_review_candidate(engine)
    data_quality_report_id, validation_report_id = _link_validation_reports(
        engine,
        candidate_review_id,
        readiness_floor="not_ready",
    )
    ready_response = json.dumps(
        {
            "summary": "Historical research diagnostics are complete.",
            "risk_flags": [],
            "overfit_warnings": [],
            "paper_trading_readiness": "ready_for_paper_research",
            "recommended_next_steps": ["run additional offline research diagnostics"],
        },
        ensure_ascii=False,
    )

    result = run_backtest_review_agent(
        engine,
        BacktestReviewRequest(candidate_review_id=candidate_review_id),
        llm_client=FakeLLMClient(ready_response),
    )

    assert result["paper_trading_readiness"] == "not_ready"
    assert result["readiness_floor_applied"] is True
    assert result["validation_report_id"] == validation_report_id
    assert result["data_quality_report_id"] == data_quality_report_id


def test_run_backtest_review_agent_rejects_non_succeeded_candidate_without_trading_rows():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id, backtest_run_id = _seed_backtest_review_candidate(
        engine,
        review_status="approved",
    )

    try:
        run_backtest_review_agent(
            engine,
            BacktestReviewRequest(
                candidate_review_id=candidate_review_id,
                backtest_run_id=backtest_run_id,
                require_validation_report=False,
            ),
            llm_client=FakeLLMClient(VALID_BACKTEST_REVIEW_RESPONSE),
        )
    except ValueError as exc:
        assert "candidate review must have backtest_succeeded status" in str(exc)
    else:
        raise AssertionError("expected non-succeeded candidate review failure")

    from quant_trading.storage.models import BrokerOrderEventORM, PaperRunORM

    with session_scope(engine) as session:
        review = AgentCandidateReviewRepository(session).get(candidate_review_id)
        agent_run = session.scalar(
            select(AgentRunORM).where(AgentRunORM.agent_type == "backtest_review")
        )
        assert review is not None
        assert review.status == "approved"
        assert review.review_agent_run_id is None
        assert agent_run is None
        assert session.query(PaperRunORM).count() == 0
        assert session.query(BrokerOrderEventORM).count() == 0


def test_run_backtest_review_agent_rejects_mismatched_backtest_run_id():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id, linked_backtest_run_id = _seed_backtest_review_candidate(engine)
    mismatched_backtest_run_id = _create_unlinked_backtest_run(engine)

    try:
        run_backtest_review_agent(
            engine,
            BacktestReviewRequest(
                candidate_review_id=candidate_review_id,
                backtest_run_id=mismatched_backtest_run_id,
                require_validation_report=False,
            ),
            llm_client=FakeLLMClient(VALID_BACKTEST_REVIEW_RESPONSE),
        )
    except ValueError as exc:
        assert "backtest_run_id does not match candidate review" in str(exc)
    else:
        raise AssertionError("expected mismatched backtest_run_id failure")

    with session_scope(engine) as session:
        review = AgentCandidateReviewRepository(session).get(candidate_review_id)
        agent_run = session.scalar(
            select(AgentRunORM).where(AgentRunORM.agent_type == "backtest_review")
        )
        assert review is not None
        assert review.status == "backtest_succeeded"
        assert review.backtest_run_id == linked_backtest_run_id
        assert review.review_agent_run_id is None
        assert agent_run is None


def test_strategy_idea_agent_persists_failure_when_llm_credentials_missing():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    try:
        run_strategy_idea_agent(
            engine,
            StrategyIdeaRequest(idea="Trend following", symbol="000001"),
            settings=AppSettings(deepseek_api_key=None),
        )
    except ValueError as exc:
        assert "DEEPSEEK_API_KEY is required for agent jobs" in str(exc)
    else:
        raise AssertionError("expected missing credential failure")

    with session_scope(engine) as session:
        row = session.scalar(select(AgentRunORM))

    assert row is not None
    assert row.status == "failed"
    assert row.agent_type == "strategy_idea"
    assert row.error_message == "DEEPSEEK_API_KEY is required for agent jobs"


def test_market_analysis_job_api_submits_agent_job(monkeypatch, legacy_sqlite_db: Path):
    from quant_trading.jobs import runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient("市场研究报告"),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    response = client.post(
        "/jobs/agents/market-analysis",
        json={"symbol": "000001", "lookback_bars": 60, "mode": "overview"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "agent_market_analysis"
    assert payload["status"] == "succeeded"
    assert payload["result_payload"]["agent_type"] == "market_analysis"


def test_strategy_idea_job_api_submits_agent_job(monkeypatch):
    from quant_trading.jobs import runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient(VALID_MA_CROSS_RESPONSE),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    response = client.post(
        "/jobs/agents/strategy-idea",
        json={"idea": "Trend pullback strategy", "symbol": "000001"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "agent_strategy_idea"
    assert payload["status"] == "succeeded"
    assert payload["result_payload"]["agent_type"] == "strategy_idea"
    assert payload["result_payload"]["validation_status"] == "passed"
    assert payload["result_payload"]["candidate_payload"]["strategy_name"] == "ma_cross"
    assert (
        payload["result_payload"]["backtest_request_payload"]["job_type"]
        == "backtest_ma_cross"
    )
    assert payload["result_payload"]["requires_human_approval"] is True


def test_backtest_review_job_api_persists_agent_run_and_creates_no_trading_rows(monkeypatch):
    from quant_trading.jobs import runtime as runtime_module
    from quant_trading.storage.models import (
        BacktestRunORM,
        BrokerOrderEventORM,
        JobRunORM,
        PaperRunORM,
        WorkflowRunORM,
    )

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient(VALID_BACKTEST_REVIEW_RESPONSE),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id, backtest_run_id = _seed_backtest_review_candidate(engine)
    client = TestClient(
        create_app(
            engine=engine,
            settings=AppSettings(
                deepseek_api_key="secret-test-key",
                job_executor="inline",
            ),
        )
    )

    response = client.post(
        "/jobs/agents/backtest-review",
        json={
            "candidate_review_id": candidate_review_id,
            "backtest_run_id": backtest_run_id,
            "require_validation_report": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "agent_backtest_review"
    assert payload["status"] == "succeeded"
    assert payload["result_payload"]["agent_type"] == "backtest_review"
    assert payload["result_payload"]["research_only"] is True
    assert payload["result_payload"]["candidate_review_id"] == candidate_review_id
    assert payload["result_payload"]["backtest_run_id"] == backtest_run_id
    assert "deepseek_api_key" not in payload["request_payload"]

    with session_scope(engine) as session:
        agent_run = session.scalar(
            select(AgentRunORM).where(AgentRunORM.agent_type == "backtest_review")
        )
        job = session.scalar(select(JobRunORM).where(JobRunORM.job_type == "agent_backtest_review"))
        workflow = session.scalar(select(WorkflowRunORM))
        review = AgentCandidateReviewRepository(session).get(candidate_review_id)
        assert agent_run is not None
        assert job is not None
        assert workflow is not None
        assert agent_run.status == "succeeded"
        assert agent_run.job_run_id == job.id
        assert review is not None
        assert review.status == "review_succeeded"
        assert review.review_agent_run_id == agent_run.id
        assert session.query(BacktestRunORM).count() == 1
        assert session.query(PaperRunORM).count() == 0
        assert session.query(BrokerOrderEventORM).count() == 0
        assert "deepseek_api_key" not in json.loads(job.request_payload)
        assert "secret-test-key" not in job.request_payload
        assert "deepseek_api_key" not in json.loads(workflow.request_payload)
        assert "secret-test-key" not in workflow.request_payload


def test_backtest_review_job_api_rejects_missing_validation_before_agent_run(monkeypatch):
    from quant_trading.jobs import runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient(VALID_BACKTEST_REVIEW_RESPONSE),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id, backtest_run_id = _seed_backtest_review_candidate(engine)
    client = TestClient(
        create_app(
            engine=engine,
            settings=AppSettings(
                deepseek_api_key="secret-test-key",
                job_executor="inline",
            ),
        )
    )

    response = client.post(
        "/jobs/agents/backtest-review",
        json={
            "candidate_review_id": candidate_review_id,
            "backtest_run_id": backtest_run_id,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "validation report is required for backtest review"
    with session_scope(engine) as session:
        assert (
            session.scalar(
                select(func.count(AgentRunORM.id)).where(
                    AgentRunORM.agent_type == "backtest_review"
                )
            )
            == 0
        )


def test_strategy_idea_candidate_job_does_not_create_trading_rows(monkeypatch):
    from quant_trading.jobs import runtime as runtime_module
    from quant_trading.storage.models import (
        BacktestRunORM,
        BrokerOrderEventORM,
        JobRunORM,
        PaperRunORM,
    )

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient(VALID_MA_CROSS_RESPONSE),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    response = client.post(
        "/jobs/agents/strategy-idea",
        json={"idea": "Trend pullback strategy", "symbol": "000001"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result_payload"]["validation_status"] == "passed"
    with session_scope(engine) as session:
        backtest_job_count = (
            session.query(JobRunORM)
            .where(JobRunORM.job_type == "backtest_ma_cross")
            .count()
        )
        assert backtest_job_count == 0
        assert session.query(BacktestRunORM).count() == 0
        assert session.query(PaperRunORM).count() == 0
        assert session.query(BrokerOrderEventORM).count() == 0


def test_agent_jobs_do_not_create_broker_order_events(monkeypatch, legacy_sqlite_db: Path):
    from quant_trading.jobs import runtime as runtime_module
    from quant_trading.storage.models import BrokerOrderEventORM

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient("市场研究报告"),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    response = client.post(
        "/jobs/agents/market-analysis",
        json={"symbol": "000001", "lookback_bars": 60},
    )

    assert response.status_code == 200
    with session_scope(engine) as session:
        assert session.query(BrokerOrderEventORM).count() == 0


def _seed_backtest_review_candidate(
    engine,
    *,
    review_status: str = "backtest_succeeded",
) -> tuple[int, int]:
    now = datetime(2026, 6, 24, 9, 0, 0)
    with session_scope(engine) as session:
        source = AgentRunRepository(session).create_running(
            agent_type="strategy_idea",
            symbol="000001",
            model_name="fake-llm",
            request_payload=json.dumps({"idea": "ma cross"}, sort_keys=True),
            job_run_id=None,
            started_at=now,
        )
        AgentRunRepository(session).mark_succeeded(
            source,
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
            finished_at=now,
            duration_ms=1,
        )
        from quant_trading.storage.models import BacktestEquityPointORM, BacktestRunORM

        run = BacktestRunORM(
            strategy_name="ma_cross",
            symbol="000001",
            initial_cash=Decimal("100000.000000"),
            final_equity=Decimal("102000.000000"),
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
                    equity=Decimal("102000.000000"),
                    cash=Decimal("102000.000000"),
                    market_value=Decimal("0.000000"),
                    drawdown=Decimal("0.010000"),
                ),
            ]
        )
        review = AgentCandidateReviewRepository(session).create_decision(
            source_agent_run_id=source.id,
            status=review_status,
            symbol="000001",
            strategy_name="ma_cross",
            candidate_payload=json.dumps(
                {"strategy_name": "ma_cross", "symbol": "000001"},
                sort_keys=True,
            ),
            backtest_request_payload=json.dumps(
                {"job_type": "backtest_ma_cross", "payload": {"symbol": "000001"}},
                sort_keys=True,
            ),
            operator="local",
            operator_note="approved for research backtest",
            decided_at=now,
            created_at=now,
        )
        review.backtest_run_id = run.id
        return review.id, run.id


def _create_unlinked_backtest_run(engine) -> int:
    from quant_trading.storage.models import BacktestRunORM

    with session_scope(engine) as session:
        run = BacktestRunORM(
            strategy_name="ma_cross",
            symbol="000002",
            initial_cash=Decimal("100000.000000"),
            final_equity=Decimal("50000.000000"),
            status="done",
            created_at=datetime(2026, 6, 24, 10, 0, 0),
        )
        session.add(run)
        session.flush()
        return run.id


def _link_validation_reports(
    engine,
    candidate_review_id: int,
    *,
    readiness_floor: str,
) -> tuple[int, int]:
    now = datetime(2026, 6, 24, 9, 5, 0)
    with session_scope(engine) as session:
        review = AgentCandidateReviewRepository(session).get(candidate_review_id)
        assert review is not None
        assert review.backtest_run_id is not None
        data_quality = DataQualityReportORM(
            candidate_review_id=candidate_review_id,
            backtest_run_id=review.backtest_run_id,
            symbol=review.symbol,
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
            candidate_review_id=candidate_review_id,
            source_backtest_run_id=review.backtest_run_id,
            data_quality_report_id=data_quality.id,
            symbol=review.symbol,
            strategy_name=review.strategy_name,
            validation_status="failed" if readiness_floor == "not_ready" else "passed",
            readiness_floor=readiness_floor,
            in_sample_metrics_payload='{"return_pct":"1.000000"}',
            out_of_sample_metrics_payload='{"return_pct":"-1.000000"}',
            walk_forward_payload='{"windows":[{"return_pct":"-1.000000"}]}',
            parameter_sensitivity_payload='{"runs":[{"return_pct":"-2.000000"}]}',
            benchmark_payload='{"excess_return_pct":"-3.000000"}',
            summary_payload=json.dumps(
                {
                    "candidate_review_id": candidate_review_id,
                    "readiness_floor": readiness_floor,
                    "reasons": [{"code": "test_floor"}],
                    "research_only": True,
                },
                sort_keys=True,
            ),
            created_at=now,
            finished_at=now,
            duration_ms=1,
        )
        session.add(validation)
        session.flush()
        review.data_quality_report_id = data_quality.id
        review.research_validation_report_id = validation.id
        return data_quality.id, validation.id
