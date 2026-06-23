# Quant Trading Live Job Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Server-Sent Events job-event streaming and lightweight dashboard live updates for queued job progress.

**Architecture:** Keep `job_events` and `job_runs` as the authoritative source of truth. Add a small API streaming helper that polls the database and emits SSE frames, expose it through `GET /jobs/{job_run_id}/stream`, then progressively enhance the server-rendered dashboard with native `EventSource` when an active job exists.

**Tech Stack:** FastAPI, Starlette `StreamingResponse`, SQLAlchemy 2.x, pytest/TestClient, server-rendered HTML, native browser `EventSource`.

---

## Baseline

```bash
cd /private/tmp/quant-stage4-runtime
git status --short --branch
```

Expected: branch `codex/quant-stage4-runtime-tmp`, clean worktree, Stage 8 design committed as `docs/superpowers/specs/2026-06-23-quant-trading-live-job-streaming-design.md`.

Primary design: `docs/superpowers/specs/2026-06-23-quant-trading-live-job-streaming-design.md`

## File Structure

Create:

- `src/quant_trading/api/job_streaming.py` - SSE formatting, stream timing clamps, job existence validation, and async database-backed event generator.
- `tests/integration/test_job_streaming.py` - SSE API behavior tests.

Modify:

- `src/quant_trading/storage/repositories.py` - add optional `after_event_id` filtering to `JobEventRepository.list_for_job()`.
- `src/quant_trading/api/routes/jobs.py` - add `GET /jobs/{job_run_id}/stream`.
- `src/quant_trading/api/routes/dashboard.py` - render active-job stream metadata and browser `EventSource` progressive enhancement.
- `tests/integration/test_runtime_auth.py` - cover authenticated access to the new stream route.
- `tests/integration/test_dashboard.py` - cover stream hook rendering and static fallback.
- `README.md` - document live job streaming endpoint and dashboard behavior.

## Task 1: Job Stream API

**Files:**

- Create: `tests/integration/test_job_streaming.py`
- Create: `src/quant_trading/api/job_streaming.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Modify: `src/quant_trading/api/routes/jobs.py`

- [ ] **Step 1: Write failing stream API tests**

Create `tests/integration/test_job_streaming.py`:

```python
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
```

- [ ] **Step 2: Run stream API tests to verify RED**

Run:

```bash
python -m pytest tests/integration/test_job_streaming.py -q
```

Expected: FAIL because `/jobs/{job_run_id}/stream` is not registered and returns `404`.

- [ ] **Step 3: Add repository filtering for streamed replay**

Modify `src/quant_trading/storage/repositories.py`. Replace `JobEventRepository.list_for_job()` with:

```python
    def list_for_job(
        self,
        job_run_id: int,
        *,
        after_event_id: int | None = None,
    ) -> list[JobEventORM]:
        statement = (
            select(JobEventORM)
            .where(JobEventORM.job_run_id == job_run_id)
            .order_by(JobEventORM.id)
        )
        if after_event_id is not None:
            statement = statement.where(JobEventORM.id > after_event_id)
        return list(self.session.scalars(statement).all())
```

Existing callers keep using `list_for_job(job_run_id)` unchanged.

- [ ] **Step 4: Add SSE streaming helper**

Create `src/quant_trading/api/job_streaming.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime
import json
import time
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import Engine

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import JobEventORM
from quant_trading.storage.repositories import JobEventRepository, JobRunRepository

TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


def ensure_job_exists(engine: Engine, job_run_id: int) -> None:
    with session_scope(engine) as session:
        if JobRunRepository(session).get(job_run_id) is None:
            raise HTTPException(status_code=404, detail="job run not found")


async def iter_job_event_sse(
    request: Request,
    engine: Engine,
    job_run_id: int,
    *,
    after_event_id: int = 0,
    poll_interval_seconds: float = 1.0,
    heartbeat_seconds: float = 15.0,
    max_idle_seconds: float | None = None,
) -> AsyncIterator[str]:
    last_event_id = max(0, after_event_id)
    poll_interval = _clamp(poll_interval_seconds, minimum=0.001, maximum=5.0)
    heartbeat_interval = _clamp(heartbeat_seconds, minimum=0.001, maximum=60.0)
    idle_limit = (
        None
        if max_idle_seconds is None
        else _clamp(max_idle_seconds, minimum=0.001, maximum=300.0)
    )
    last_emit_at = time.monotonic()
    idle_started_at = last_emit_at

    while True:
        if await request.is_disconnected():
            break

        events, status = _load_events_and_status(engine, job_run_id, last_event_id)
        emitted_event = False
        for event in events:
            last_event_id = event.id
            emitted_event = True
            last_emit_at = time.monotonic()
            yield format_sse("job_event", _job_event_payload(event), event_id=event.id)

        if emitted_event:
            idle_started_at = time.monotonic()

        if status in TERMINAL_JOB_STATUSES:
            yield format_sse("stream_end", {"job_run_id": job_run_id, "status": status})
            break

        now = time.monotonic()
        if now - last_emit_at >= heartbeat_interval:
            yield format_sse("heartbeat", {})
            last_emit_at = now

        if idle_limit is not None and now - idle_started_at >= idle_limit:
            break

        await asyncio.sleep(poll_interval)


def format_sse(event_name: str, data: dict[str, Any], *, event_id: int | None = None) -> str:
    lines = [f"event: {event_name}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
    for line in encoded.splitlines() or ["{}"]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _load_events_and_status(
    engine: Engine,
    job_run_id: int,
    after_event_id: int,
) -> tuple[list[JobEventORM], str | None]:
    with session_scope(engine) as session:
        job = JobRunRepository(session).get(job_run_id)
        if job is None:
            return [], None
        events = JobEventRepository(session).list_for_job(
            job_run_id,
            after_event_id=after_event_id,
        )
        return events, job.status


def _job_event_payload(row: JobEventORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_run_id": row.job_run_id,
        "event_type": row.event_type,
        "message": row.message,
        "progress": row.progress,
        "payload": _json_loads(row.payload),
        "created_at": _iso(row.created_at),
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)
```

- [ ] **Step 5: Add stream route**

Modify `src/quant_trading/api/routes/jobs.py`.

Add this import:

```python
from fastapi.responses import StreamingResponse

from quant_trading.api.job_streaming import ensure_job_exists, iter_job_event_sse
```

Insert this route after `list_job_events()` and before `get_job()` so it is not captured by `/{job_run_id}`:

```python
@router.get("/{job_run_id}/stream")
def stream_job_events(
    job_run_id: int,
    request: Request,
    after_event_id: int = 0,
    poll_interval_seconds: float = 1.0,
    heartbeat_seconds: float = 15.0,
    max_idle_seconds: float | None = None,
) -> StreamingResponse:
    ensure_job_exists(request.app.state.engine, job_run_id)
    return StreamingResponse(
        iter_job_event_sse(
            request,
            request.app.state.engine,
            job_run_id,
            after_event_id=after_event_id,
            poll_interval_seconds=poll_interval_seconds,
            heartbeat_seconds=heartbeat_seconds,
            max_idle_seconds=max_idle_seconds,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
```

- [ ] **Step 6: Verify GREEN for stream API**

Run:

```bash
python -m pytest tests/integration/test_job_streaming.py -q
python -m py_compile src/quant_trading/api/job_streaming.py src/quant_trading/api/routes/jobs.py src/quant_trading/storage/repositories.py
```

Expected: `4 passed`; py_compile exits `0`.

- [ ] **Step 7: Spec review for Task 1**

Run:

```bash
rg -n "stream|after_event_id|job_event|stream_end|text/event-stream|ensure_job_exists|iter_job_event_sse" src/quant_trading/api src/quant_trading/storage tests/integration/test_job_streaming.py docs/superpowers/specs/2026-06-23-quant-trading-live-job-streaming-design.md
```

Required evidence:

- `GET /jobs/{job_run_id}/stream` exists.
- SSE messages include `job_event` and `stream_end`.
- `after_event_id` skips earlier events.
- Missing jobs return `404`.
- The stream reads from `job_events` and does not add Redis, websocket, or broker execution.

- [ ] **Step 8: Quality review for Task 1**

Run:

```bash
git diff -- src/quant_trading/api/job_streaming.py src/quant_trading/api/routes/jobs.py src/quant_trading/storage/repositories.py tests/integration/test_job_streaming.py
```

Confirm:

- `routes/jobs.py` remains thin and delegates streaming details.
- Stream helper sends sanitized event payloads matching `/jobs/{job_run_id}/events`.
- Route order places `/stream` before `/{job_run_id}`.
- Timing query parameters are clamped.
- Tests use in-memory SQLite only and do not require Redis or provider network access.

- [ ] **Step 9: Commit Task 1**

Run:

```bash
git add src/quant_trading/api/job_streaming.py src/quant_trading/api/routes/jobs.py src/quant_trading/storage/repositories.py tests/integration/test_job_streaming.py
git commit -m "feat: stream job events over sse"
```

## Task 2: Stream Auth Coverage

**Files:**

- Modify: `tests/integration/test_runtime_auth.py`

- [ ] **Step 1: Write valid-auth and unauthorized stream tests**

Append to `tests/integration/test_runtime_auth.py`:

```python
def test_job_stream_api_requires_auth_when_enabled():
    client = make_client()

    response = client.get("/jobs/1/stream")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_job_stream_api_allows_bearer_token_when_enabled():
    client = make_client()

    response = client.get(
        "/jobs/1/stream",
        headers={"Authorization": "Bearer local-token"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "job run not found"}
```

The second test uses `404` as positive auth evidence: the token passed middleware and reached the route, where the in-memory database has no job id `1`.

- [ ] **Step 2: Run auth tests**

Run:

```bash
python -m pytest tests/integration/test_runtime_auth.py -q
```

Expected: all auth tests pass after Task 1 exists. If `test_job_stream_api_allows_bearer_token_when_enabled` returns `401`, fix auth handling before proceeding.

- [ ] **Step 3: Spec review for Task 2**

Run:

```bash
rg -n "job_stream|/jobs/1/stream|Authorization|Unauthorized|job run not found" tests/integration/test_runtime_auth.py docs/superpowers/specs/2026-06-23-quant-trading-live-job-streaming-design.md
```

Required evidence: stream route is protected by existing token auth and a valid token reaches the route.

- [ ] **Step 4: Quality review for Task 2**

Run:

```bash
git diff -- tests/integration/test_runtime_auth.py
```

Confirm the tests do not create external dependencies and do not require a real job to prove middleware behavior.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add tests/integration/test_runtime_auth.py
git commit -m "test: cover job stream auth"
```

## Task 3: Dashboard Progressive Enhancement

**Files:**

- Modify: `src/quant_trading/api/routes/dashboard.py`
- Modify: `tests/integration/test_dashboard.py`

- [ ] **Step 1: Write failing dashboard stream hook tests**

Append to `tests/integration/test_dashboard.py`:

```python
def test_dashboard_renders_job_event_stream_hook_for_active_job():
    from datetime import UTC, datetime

    from quant_trading.jobs.runtime import MARKET_DATA_SYNC, job_payload_dumps
    from quant_trading.storage.repositories import JobEventRepository, JobRunRepository

    client, engine = make_client()
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        job = JobRunRepository(session).create_queued(
            MARKET_DATA_SYNC,
            job_payload_dumps({"provider": "fake", "symbol": "000001"}),
            now,
        )
        JobRunRepository(session).mark_running(job, started_at=now)
        event = JobEventRepository(session).record(
            job.id,
            "running",
            "job started",
            progress=10,
            created_at=now,
        )
        job_id = job.id
        event_id = event.id

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert f'data-job-stream-url="/jobs/{job_id}/stream?after_event_id={event_id}"' in html
    assert 'id="job-stream-status"' in html
    assert 'new EventSource' in html
    assert 'id="job-events-body"' in html


def test_dashboard_omits_job_event_stream_hook_without_active_job():
    client, _ = make_client()

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "data-job-stream-url" not in response.text
```

- [ ] **Step 2: Run dashboard stream hook tests to verify RED**

Run:

```bash
python -m pytest tests/integration/test_dashboard.py::test_dashboard_renders_job_event_stream_hook_for_active_job tests/integration/test_dashboard.py::test_dashboard_omits_job_event_stream_hook_without_active_job -q
```

Expected: command exits nonzero because the first test fails: the dashboard has no stream metadata or script.

- [ ] **Step 3: Add active job stream state**

Modify `src/quant_trading/api/routes/dashboard.py`.

Add near `router = APIRouter(tags=["dashboard"])`:

```python
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}
```

Refactor `_collect_state()` so job rows are held in local variables before returning:

```python
            job_runs = JobRunRepository(session).list_recent(limit=20)
            job_events = JobEventRepository(session).list_recent(limit=30)
            active_job = _active_job(job_runs)
            active_job_latest_event_id = (
                session.scalar(
                    select(func.max(JobEventORM.id)).where(
                        JobEventORM.job_run_id == active_job.id
                    )
                )
                if active_job is not None
                else None
            )
```

Then return these values in the state dictionary:

```python
            "job_runs": job_runs,
            "job_events": job_events,
            "active_job": active_job,
            "active_job_latest_event_id": active_job_latest_event_id,
```

Add this helper after `_latest()`:

```python
def _active_job(rows: list[JobRunORM]) -> JobRunORM | None:
    for row in rows:
        if row.status not in TERMINAL_JOB_STATUSES:
            return row
    return None
```

- [ ] **Step 4: Render stream metadata and script**

Modify `_render_dashboard()` so the opening `<main>` includes active stream attributes:

```python
<main{_job_stream_attrs(state)}>
```

Add the script before `</main>`:

```python
  {_job_event_stream_script(state)}
```

Replace `_job_events_table()` with:

```python
def _job_events_table(state: dict[str, Any]) -> str:
    rows = state["job_events"]
    head = "".join(
        f"<th>{_e(column)}</th>"
        for column in ["ID", "Job", "Type", "Message", "Progress", "Created"]
    )
    if not rows:
        body = '<tr><td class="empty" colspan="6">No rows</td></tr>'
    else:
        body = "".join(
            f'<tr data-event-id="{_e(row.id)}">'
            + "".join(
                _table_cell(value)
                for value in [
                    f"#{row.id}",
                    f"#{row.job_run_id}",
                    row.event_type,
                    row.message,
                    f"{row.progress}%" if row.progress is not None else "",
                    row.created_at,
                ]
            )
            + "</tr>"
            for row in rows
        )
    status = (
        '<span id="job-stream-status" class="stream-status">waiting</span>'
        if state.get("active_job") is not None
        else ""
    )
    return (
        f"<section><h2>Job Events {status}</h2>"
        f'<table id="job-events-table"><thead><tr>{head}</tr></thead>'
        f'<tbody id="job-events-body">{body}</tbody></table></section>'
    )
```

Add these helpers near the dashboard rendering helpers:

```python
def _job_stream_attrs(state: dict[str, Any]) -> str:
    active_job = state.get("active_job")
    if active_job is None:
        return ""
    latest_event_id = state.get("active_job_latest_event_id") or 0
    stream_url = f"/jobs/{active_job.id}/stream?after_event_id={latest_event_id}"
    return (
        f' data-job-stream-url="{_e(stream_url)}"'
        f' data-job-stream-job-id="{_e(active_job.id)}"'
        f' data-job-stream-after-event-id="{_e(latest_event_id)}"'
    )


def _job_event_stream_script(state: dict[str, Any]) -> str:
    if state.get("active_job") is None:
        return ""
    return """
  <script>
  (function () {
    const root = document.querySelector("[data-job-stream-url]");
    const body = document.getElementById("job-events-body");
    const status = document.getElementById("job-stream-status");
    if (!root || !body || !status || !window.EventSource) {
      return;
    }
    const seen = new Set(Array.from(body.querySelectorAll("[data-event-id]")).map((row) => row.dataset.eventId));
    const source = new EventSource(root.dataset.jobStreamUrl);
    status.textContent = "streaming";

    function appendCell(row, value) {
      const cell = document.createElement("td");
      cell.textContent = value == null ? "" : String(value);
      row.appendChild(cell);
    }

    source.addEventListener("job_event", function (message) {
      const event = JSON.parse(message.data);
      const id = String(event.id);
      if (seen.has(id)) {
        return;
      }
      seen.add(id);
      const row = document.createElement("tr");
      row.dataset.eventId = id;
      appendCell(row, "#" + event.id);
      appendCell(row, "#" + event.job_run_id);
      appendCell(row, event.event_type);
      appendCell(row, event.message);
      appendCell(row, event.progress == null ? "" : event.progress + "%");
      appendCell(row, event.created_at);
      const empty = body.querySelector(".empty");
      if (empty) {
        body.textContent = "";
      }
      body.insertBefore(row, body.firstChild);
      status.textContent = "live";
    });

    source.addEventListener("heartbeat", function () {
      status.textContent = "live";
    });

    source.addEventListener("stream_end", function () {
      status.textContent = "closed";
      source.close();
    });

    source.onerror = function () {
      status.textContent = "reconnecting";
    };
  }());
  </script>"""
```

Do not add a `json` import for this dashboard task; the script above is static and all browser-inserted values use `textContent`.

- [ ] **Step 5: Verify GREEN for dashboard**

Run:

```bash
python -m pytest tests/integration/test_dashboard.py::test_dashboard_renders_job_event_stream_hook_for_active_job tests/integration/test_dashboard.py::test_dashboard_omits_job_event_stream_hook_without_active_job -q
python -m pytest tests/integration/test_dashboard.py -q
python -m py_compile src/quant_trading/api/routes/dashboard.py
```

Expected: dashboard stream hook tests pass; full dashboard integration file passes; py_compile exits `0`.

- [ ] **Step 6: Spec review for Task 3**

Run:

```bash
rg -n "data-job-stream-url|job-stream-status|EventSource|job-events-body|active_job|TERMINAL_JOB_STATUSES" src/quant_trading/api/routes/dashboard.py tests/integration/test_dashboard.py docs/superpowers/specs/2026-06-23-quant-trading-live-job-streaming-design.md
```

Required evidence:

- Dashboard renders stream metadata only when a non-terminal job exists.
- Dashboard uses native `EventSource`.
- Job-event rows can be appended without a page refresh.
- Static dashboard remains available when no active job exists.

- [ ] **Step 7: Quality review for Task 3**

Run:

```bash
git diff -- src/quant_trading/api/routes/dashboard.py tests/integration/test_dashboard.py
```

Confirm:

- HTML output still escapes server-rendered values through `_e()` and `_table_cell()`.
- Browser-inserted values use `textContent`, not raw HTML.
- Dashboard stays server-rendered with a small progressive enhancement.
- No frontend dependency, websocket code, broker execution, or schedule-control form was added.

- [ ] **Step 8: Commit Task 3**

Run:

```bash
git add src/quant_trading/api/routes/dashboard.py tests/integration/test_dashboard.py
git commit -m "feat: add live job stream dashboard hook"
```

## Task 4: README And Final Verification

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Update README endpoint list**

In `README.md`, add the stream endpoint to the API endpoint list after `/jobs/{job_run_id}/events`:

```text
http://localhost:8000/jobs/{job_run_id}/stream
```

- [ ] **Step 2: Document live job streaming**

In `README.md`, add this subsection after "Scheduled Operations And Job Control":

```markdown
## Live Job Progress Streaming

Stage 8 adds an SSE stream for job-event timelines:

- `GET /jobs/{job_run_id}/stream` streams `job_event`, `heartbeat`, and `stream_end` messages.
- `after_event_id` lets clients resume from the last event they processed.
- The dashboard automatically subscribes to the most recent active job when browser `EventSource` is available.

Example:

```bash
curl -N "http://127.0.0.1:8000/jobs/1/stream?after_event_id=0"
```

The stream is a read-side operational view over `job_events`. It does not add websocket command channels, broker execution, market tick streaming, or provider credential storage.
```

- [ ] **Step 3: Run focused Stage 8 verification**

Run:

```bash
python -m pytest tests/integration/test_job_streaming.py tests/integration/test_runtime_auth.py tests/integration/test_dashboard.py -q
python -m py_compile src/quant_trading/api/job_streaming.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/routes/dashboard.py src/quant_trading/storage/repositories.py
docker compose config
git diff --check
```

Expected: pytest exits `0`; py_compile exits `0`; compose config exits `0`; diff check exits `0`.

- [ ] **Step 4: Run full verification**

Run:

```bash
python -m pytest -q
docker compose config
git status --short --branch
```

Expected: full test suite exits `0`; Docker Compose config exits `0`; git status shows only intended README changes before commit.

- [ ] **Step 5: Spec review for Task 4**

Run:

```bash
rg -n "Live Job Progress Streaming|/jobs/\\{job_run_id\\}/stream|after_event_id|job_event|heartbeat|stream_end|EventSource|websocket command|broker execution|market tick" README.md src tests docs/superpowers/specs/2026-06-23-quant-trading-live-job-streaming-design.md
```

Required evidence:

- README documents the stream endpoint and resume parameter.
- Dashboard and API evidence map to the Stage 8 acceptance criteria.
- Safety boundaries are present: no websocket command channel, no broker execution, no market tick streaming.

- [ ] **Step 6: Quality review for Task 4**

Run:

```bash
git diff -- README.md src/quant_trading/api src/quant_trading/storage tests/integration
```

Confirm:

- No real Redis, AkShare, yfinance, CCXT, broker, or exchange dependency is required by tests.
- No secrets, tokens, provider credentials, raw provider payloads, or tracebacks are streamed.
- API code remains thin.
- Dashboard enhancement is progressive and safe without JavaScript.
- No websocket, pub/sub, or external broadcaster dependency was introduced.

- [ ] **Step 7: Commit Task 4**

Run:

```bash
git add README.md
git commit -m "docs: document live job streaming"
```

## Final Branch Verification

After all tasks are committed, run:

```bash
python -m pytest -q
python -m py_compile src/quant_trading/api/job_streaming.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/routes/dashboard.py src/quant_trading/storage/repositories.py
docker compose config
git diff --check
git status --short --branch
```

Expected:

- Full test suite exits `0`.
- py_compile exits `0`.
- Docker Compose config exits `0`.
- diff check exits `0`.
- Worktree is clean and branch is ahead of remote.

## Completion Notes

Stage 8 is complete only when:

- `/jobs/{job_run_id}/stream` emits `job_event`, `heartbeat`, and `stream_end` SSE frames.
- Clients can resume with `after_event_id`.
- Terminal jobs close cleanly.
- Stream route is protected by existing auth.
- Dashboard subscribes to the most recent active job and can append new event rows.
- README documents the feature and safety boundaries.
- AGENTS.md-required Spec review and quality review have passed for each implementation task.
- Full tests and Docker Compose config pass.
