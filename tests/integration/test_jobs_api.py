from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobRunORM


def make_client(settings: AppSettings | None = None):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    settings = settings or AppSettings(job_executor="inline")
    return TestClient(create_app(engine=engine, settings=settings)), engine


def test_inline_import_job_api_returns_succeeded_job(legacy_sqlite_db: Path):
    client, engine = make_client()

    response = client.post("/jobs/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "import_legacy"
    assert payload["status"] == "succeeded"
    assert payload["progress"] == 100
    assert payload["workflow_run_id"] == 1
    with session_scope(engine) as session:
        assert session.scalar(select(JobRunORM.status)) == "succeeded"


def test_job_read_apis_filter_and_get_jobs(legacy_sqlite_db: Path):
    client, _ = make_client()
    created = client.post("/jobs/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)}).json()

    list_response = client.get("/jobs", params={"status": "succeeded", "job_type": "import_legacy"})
    get_response = client.get(f"/jobs/{created['id']}")
    missing_response = client.get("/jobs/999")

    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [created["id"]]
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "job run not found"}


def test_rq_executor_enqueues_without_running(monkeypatch, legacy_sqlite_db: Path):
    class FakeRQJob:
        id = "rq-test-1"

    class FakeQueue:
        def __init__(self):
            self.enqueued = []

        def enqueue(self, func, database_url, job_run_id):
            self.enqueued.append((func, database_url, job_run_id))
            return FakeRQJob()

    fake_queue = FakeQueue()

    from quant_trading.api.routes import jobs as jobs_route

    monkeypatch.setattr(jobs_route, "make_queue", lambda redis_url: fake_queue)
    settings = AppSettings(job_executor="rq", redis_url="redis://fake:6379/0")
    client, engine = make_client(settings=settings)

    response = client.post("/jobs/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["rq_job_id"] == "rq-test-1"
    assert fake_queue.enqueued[0][1] == settings.database_url
    with session_scope(engine) as session:
        row = session.get(JobRunORM, payload["id"])
        assert row.status == "queued"
        assert row.rq_job_id == "rq-test-1"


def test_jobs_require_auth_when_enabled():
    client, _ = make_client(AppSettings(require_auth=True, api_token="local-token"))

    response = client.get("/jobs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
