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
        llm_client=FakeLLMClient(
            '{"thesis":"trend pullback","entry_rules":["pullback"],"exit_rules":["stop"],'
            '"risk_controls":["size"],"parameters_to_test":["lookback"],'
            '"data_requirements":["daily bars"],"failure_modes":["range"],'
            '"backtest_readiness":"ready"}'
        ),
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
    assert result["spec"]["thesis"] == "trend pullback"


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
        lambda settings: FakeLLMClient(
            '{"thesis":"trend","entry_rules":["x"],"exit_rules":["y"],'
            '"risk_controls":["z"],"parameters_to_test":["p"],'
            '"data_requirements":["daily"],"failure_modes":["noise"],'
            '"backtest_readiness":"ready"}'
        ),
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
