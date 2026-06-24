from datetime import datetime
import json

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import AgentRunRepository


def make_client_with_agent_run():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    with session_scope(engine) as session:
        row = AgentRunRepository(session).create_running(
            agent_type="market_analysis",
            symbol="000001",
            model_name="fake-llm",
            request_payload=json.dumps({"symbol": "000001"}),
            job_run_id=1,
            started_at=datetime(2026, 6, 24, 9, 0, 0),
        )
        AgentRunRepository(session).mark_succeeded(
            row,
            metrics_payload=json.dumps({"bar_count": 60}),
            result_payload=json.dumps({"research_only": True}),
            finished_at=datetime(2026, 6, 24, 9, 0, 1),
            duration_ms=1000,
        )
        agent_run_id = row.id
    return TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline"))), agent_run_id


def test_agent_runs_api_lists_and_gets_runs():
    client, agent_run_id = make_client_with_agent_run()

    list_response = client.get("/agent-runs", params={"agent_type": "market_analysis"})
    get_response = client.get(f"/agent-runs/{agent_run_id}")
    missing_response = client.get("/agent-runs/999")

    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [agent_run_id]
    assert get_response.status_code == 200
    assert get_response.json()["id"] == agent_run_id
    assert get_response.json()["metrics_payload"] == {"bar_count": 60}
    assert get_response.json()["result_payload"] == {"research_only": True}
    assert missing_response.status_code == 404
