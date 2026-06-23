from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    settings = AppSettings(job_executor="rq", redis_url="redis://fake:6379/0")
    return TestClient(create_app(engine, settings))


def test_schedule_api_create_list_patch_and_get_missing():
    client = make_client()
    created = client.post(
        "/job-schedules",
        json={
            "name": "daily-000001-sync",
            "job_type": "market_data_sync",
            "request_payload": {"provider": "akshare", "symbol": "000001"},
            "interval_seconds": 86400,
            "next_run_at": "2026-06-23T09:30:00",
        },
    )
    listed = client.get("/job-schedules")
    patched = client.patch(f"/job-schedules/{created.json()['id']}", json={"enabled": False})
    missing = client.get("/job-schedules/99")

    assert created.status_code == 200
    body = created.json()
    assert body["locked_until"] is None
    assert body["locked_by"] is None
    assert body["lock_acquired_at"] is None
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "daily-000001-sync"
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert missing.status_code == 404


def test_schedule_api_rejects_invalid_schedule():
    client = make_client()
    response = client.post(
        "/job-schedules",
        json={
            "name": "bad",
            "job_type": "paper_run_tick",
            "request_payload": {},
            "interval_seconds": 30,
            "next_run_at": "2026-06-23T09:30:00",
        },
    )

    assert response.status_code == 400
