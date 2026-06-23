from datetime import UTC, datetime

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.jobs.runtime import MARKET_DATA_SYNC, job_payload_dumps
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository


def make_client(settings: AppSettings | None = None):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    settings = settings or AppSettings(job_executor="inline")
    return TestClient(create_app(engine=engine, settings=settings)), engine


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _seed_terminal_job(engine):
    now = _now()
    with session_scope(engine) as session:
        job_repo = JobRunRepository(session)
        event_repo = JobEventRepository(session)
        job = job_repo.create_queued(
            MARKET_DATA_SYNC,
            job_payload_dumps({"provider": "fake", "symbol": "000001"}),
            now,
        )
        queued = event_repo.record(job.id, "queued", "job queued", progress=0, created_at=now)
        progress = event_repo.record(
            job.id,
            "progress",
            "stored provider bars",
            progress=90,
            created_at=now,
        )
        job_repo.mark_succeeded(
            job,
            result_payload=job_payload_dumps({"imported_bars": 1}),
            workflow_run_id=None,
            finished_at=now,
            duration_ms=5,
        )
        succeeded = event_repo.record(
            job.id,
            "succeeded",
            "job succeeded",
            progress=100,
            created_at=now,
        )
        return job.id, [queued.id, progress.id, succeeded.id]


def test_job_stream_sends_existing_events_and_terminal_end():
    client, engine = make_client()
    job_run_id, event_ids = _seed_terminal_job(engine)

    response = client.get(
        f"/jobs/{job_run_id}/stream",
        params={"poll_interval_seconds": 0.001, "heartbeat_seconds": 60},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert text.count("event: job_event") == 3
    assert f"id: {event_ids[0]}" in text
    assert f"id: {event_ids[1]}" in text
    assert f"id: {event_ids[2]}" in text
    assert '"event_type":"queued"' in text
    assert '"event_type":"progress"' in text
    assert '"event_type":"succeeded"' in text
    assert "event: stream_end" in text
    assert '"status":"succeeded"' in text


def test_job_stream_after_event_id_skips_already_processed_events():
    client, engine = make_client()
    job_run_id, event_ids = _seed_terminal_job(engine)

    response = client.get(
        f"/jobs/{job_run_id}/stream",
        params={
            "after_event_id": event_ids[0],
            "poll_interval_seconds": 0.001,
            "heartbeat_seconds": 60,
        },
    )

    assert response.status_code == 200
    text = response.text
    assert f"id: {event_ids[0]}" not in text
    assert f"id: {event_ids[1]}" in text
    assert f"id: {event_ids[2]}" in text
    assert text.count("event: job_event") == 2
    assert "event: stream_end" in text


def test_job_stream_missing_job_returns_404():
    client, _ = make_client()

    response = client.get("/jobs/999/stream")

    assert response.status_code == 404
    assert response.json() == {"detail": "job run not found"}


def test_job_stream_with_valid_token_when_auth_enabled():
    settings = AppSettings(require_auth=True, api_token="local-token")
    client, engine = make_client(settings)
    job_run_id, _ = _seed_terminal_job(engine)

    response = client.get(
        f"/jobs/{job_run_id}/stream",
        headers={"Authorization": "Bearer local-token"},
        params={"poll_interval_seconds": 0.001, "heartbeat_seconds": 60},
    )

    assert response.status_code == 200
    assert "event: job_event" in response.text
