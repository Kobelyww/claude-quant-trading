from datetime import UTC, datetime
import json

from quant_trading.jobs.runtime import IMPORT_LEGACY, job_payload_dumps
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import JobEventORM
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_job_event_repository_records_and_lists_timeline():
    engine = make_engine_with_schema()
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        job = JobRunRepository(session).create_queued(
            IMPORT_LEGACY,
            job_payload_dumps({"legacy_db_path": "legacy.sqlite3"}),
            now,
        )
        repo = JobEventRepository(session)
        repo.record(
            job.id,
            "queued",
            "job queued",
            progress=0,
            payload={"source": "api"},
            created_at=now,
        )
        repo.record(job.id, "running", "job started", progress=10, payload={}, created_at=now)

    with session_scope(engine) as session:
        rows = JobEventRepository(session).list_for_job(1)
        recent = JobEventRepository(session).list_recent(limit=1)
        raw = session.get(JobEventORM, 1)

        assert [event.event_type for event in rows] == ["queued", "running"]
        assert [event.event_type for event in recent] == ["running"]
        assert raw.message == "job queued"
        assert raw.progress == 0
        assert json.loads(raw.payload) == {"source": "api"}
