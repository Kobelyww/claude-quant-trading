import json
from datetime import datetime

from sqlalchemy import select

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import AgentRunORM
from quant_trading.storage.repositories import AgentRunRepository


def make_memory_engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_agent_run_repository_creates_succeeds_lists_and_gets_run():
    engine = make_memory_engine()
    started = datetime(2026, 6, 24, 9, 0, 0)
    finished = datetime(2026, 6, 24, 9, 0, 1)

    with session_scope(engine) as session:
        repo = AgentRunRepository(session)
        row = repo.create_running(
            agent_type="market_analysis",
            symbol="000001",
            model_name="fake-model",
            request_payload='{"symbol":"000001"}',
            job_run_id=7,
            started_at=started,
        )
        repo.mark_succeeded(
            row,
            metrics_payload='{"bar_count":121}',
            result_payload='{"research_only":true}',
            finished_at=finished,
            duration_ms=1000,
        )
        run_id = row.id

    with session_scope(engine) as session:
        repo = AgentRunRepository(session)
        loaded = repo.get(run_id)
        rows = repo.list_recent(agent_type="market_analysis", status="succeeded", symbol="000001")

    assert loaded is not None
    assert loaded.status == "succeeded"
    assert loaded.error_message is None
    assert loaded.job_run_id == 7
    assert json.loads(loaded.metrics_payload) == {"bar_count": 121}
    assert [row.id for row in rows] == [run_id]


def test_agent_run_repository_marks_failed_with_capped_error():
    engine = make_memory_engine()
    started = datetime(2026, 6, 24, 9, 0, 0)
    finished = datetime(2026, 6, 24, 9, 0, 1)

    with session_scope(engine) as session:
        repo = AgentRunRepository(session)
        row = repo.create_running(
            agent_type="strategy_idea",
            symbol=None,
            model_name="fake-model",
            request_payload='{"idea":"x"}',
            job_run_id=None,
            started_at=started,
        )
        repo.mark_failed(row, "x" * 1200, finished_at=finished, duration_ms=1000)
        run_id = row.id

    with session_scope(engine) as session:
        row = session.scalar(select(AgentRunORM).where(AgentRunORM.id == run_id))

    assert row is not None
    assert row.status == "failed"
    assert len(row.error_message) == 1000
