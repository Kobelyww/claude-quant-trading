import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.agents.llm import FakeLLMClient
from quant_trading.agents.models import MarketAnalysisRequest, StrategyIdeaRequest
from quant_trading.agents.service import run_market_analysis_agent, run_strategy_idea_agent
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import AgentRunORM


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


def test_strategy_idea_candidate_job_does_not_create_trading_rows(monkeypatch):
    from quant_trading.jobs import runtime as runtime_module
    from quant_trading.storage.models import (
        BacktestRunORM,
        BrokerOrderEventORM,
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
