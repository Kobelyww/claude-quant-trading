from datetime import UTC, datetime

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import DataSyncRunRepository


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine=engine)), engine


def seed_sync_run(engine):
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        row = repo.create_running(
            "akshare", "000001", "a_stock", "stock", "CNY", "SZSE", None, None, 1, now
        )
        repo.mark_succeeded(row, imported_bars=10, finished_at=now, duration_ms=20)
        return row.id


def test_data_sync_read_apis_filter_and_get_runs():
    client, engine = make_client()
    sync_run_id = seed_sync_run(engine)

    list_response = client.get("/data-sync-runs", params={"provider": "akshare", "symbol": "000001"})
    get_response = client.get(f"/data-sync-runs/{sync_run_id}")
    missing_response = client.get("/data-sync-runs/999")

    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [sync_run_id]
    assert get_response.status_code == 200
    assert get_response.json()["imported_bars"] == 10
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "data sync run not found"}
