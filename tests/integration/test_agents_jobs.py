from pathlib import Path

from sqlalchemy import select

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
