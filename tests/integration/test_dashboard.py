from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from quant_trading.api.main import create_app
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    OperatorApprovalRequestORM,
    PaperAccountORM,
    PaperRunORM,
    SafetyIncidentORM,
)
from quant_trading.storage.repositories import AgentLearningMemoryRepository


def make_client():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(engine)), engine


def test_dashboard_renders_workflow_forms_and_empty_state():
    client, _ = make_client()

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Operations Workbench" in html
    assert 'action="/dashboard/actions/import-legacy"' in html
    assert 'action="/dashboard/actions/backtests/ma-cross"' in html
    assert 'action="/dashboard/actions/paper/accounts"' in html
    assert 'action="/dashboard/actions/paper/runs/ma-cross"' in html
    assert 'action="/dashboard/actions/paper/tick"' in html
    assert "Operations Safety" in html
    assert "inactive" in html
    assert "Broker Mode simulated" in html
    assert "Trading Enabled false" in html
    assert "Safe For Live false" in html
    assert "Backtest Runs" in html
    assert "Paper Accounts" in html


def test_dashboard_displays_agent_intelligence_section():
    client, _ = make_client()

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Agent Intelligence" in html
    assert "Active Strategy Skills" in html
    assert "Recent Learning Memories" in html
    assert "Recent Review Board Runs" in html


def test_dashboard_escapes_agent_intelligence_memory_content():
    client, engine = make_client()
    now = datetime(2026, 7, 6, 9, 30, 0)
    with session_scope(engine) as session:
        AgentLearningMemoryRepository(session).get_or_create_active(
            memory_type="operator_decision",
            scope="global",
            source_type="candidate_review",
            source_id=77,
            reason_code="html_escape",
            title="<strong>memory title</strong>",
            content="review <script>alert(1)</script> content",
            evidence_payload={"candidate_review_id": 77},
            confidence=Decimal("1"),
            importance=Decimal("0.5"),
            now=now,
        )

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "&lt;strong&gt;memory title&lt;/strong&gt;" in html
    assert "review &lt;script&gt;alert(1)&lt;/script&gt; content" in html
    assert "<strong>memory title</strong>" not in html
    assert "<script>alert(1)</script>" not in html


def test_dashboard_displays_operations_safety_posture():
    client, engine = make_client()
    now = datetime(2026, 6, 26, 9, 30, 0)

    client.post(
        "/ops/kill-switch/enable",
        json={"operator": "risk lead", "reason": "halt for incident review"},
    )
    with session_scope(engine) as session:
        intent = ExecutionOrderIntentORM(
            source_type="paper_run",
            source_id=7,
            paper_run_id=None,
            paper_order_id=None,
            client_order_id="dashboard-order-1",
            symbol="000001",
            instrument_id=1,
            side="buy",
            order_type="market",
            quantity=100,
            estimated_price=Decimal("10"),
            estimated_notional=Decimal("1000"),
            broker_mode="simulated",
            status="approval_required",
            risk_profile_name="default",
            risk_summary_payload="{}",
            approval_required=True,
            created_at=now,
            updated_at=now,
        )
        session.add(intent)
        session.flush()
        approval = OperatorApprovalRequestORM(
            resource_type="execution_order_intent",
            resource_id=intent.id,
            status="pending",
            reason_code="manual_approval_required_notional",
            requested_by="policy",
            requested_at=now,
        )
        session.add(approval)
        session.flush()
        intent.approval_request_id = approval.id
        session.add(
            ExecutionOrderDecisionORM(
                order_intent_id=intent.id,
                decision_type="approval_required",
                reason_code="manual_approval_required_notional",
                message="operator approval required before simulated submission",
                policy_payload="{}",
                created_at=now,
            )
        )
        session.add(
            SafetyIncidentORM(
                severity="critical",
                category="execution_safety",
                status="open",
                resource_type="execution_order_intent",
                resource_id=intent.id,
                reason_code="provider_stale",
                message="provider data stale during dashboard review",
                payload="{}",
                created_at=now,
            )
        )
        session.add(
            SafetyIncidentORM(
                severity="warning",
                category="readiness",
                status="open",
                resource_type="execution_order_intent",
                resource_id=intent.id,
                reason_code="approval_pending",
                message="warning incident visible during dashboard review",
                payload="{}",
                created_at=now,
            )
        )

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Operations Safety" in html
    assert "Kill Switch" in html
    assert "active" in html
    assert "Safe For Simulated" in html
    assert "Safe For Dry Run" in html
    assert "Safe For Live" in html
    assert "false" in html
    assert "Pending Approvals" in html
    assert "Open Critical Incidents" in html
    assert "Open Critical Incidents 1" in html
    assert "Open Warning Incidents" in html
    assert "Open Warning Incidents 1" in html
    assert "halt for incident review" in html
    assert "provider data stale during dashboard review" in html
    assert "warning incident visible during dashboard review" in html
    assert "Recent Safety Decisions" in html
    assert "Recent Order Intents" in html
    assert "Recent Approval Requests" in html
    assert "Recent Safety Incidents" in html
    assert "Recent Kill Switch Events" in html
    assert "manual_approval_required_notional" in html
    assert "dashboard-order-1" in html


def test_dashboard_displays_seeded_workflow_state(legacy_sqlite_db: Path):
    client, _ = make_client()
    client.post(
        "/workflows/import-legacy",
        json={"legacy_db_path": str(legacy_sqlite_db)},
    )
    backtest_response = client.post(
        "/workflows/backtests/ma-cross",
        json={
            "symbol": "000001",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
            "initial_cash": "100000",
        },
    )
    account_response = client.post(
        "/workflows/paper/accounts",
        json={"name": "Dashboard Paper", "initial_cash": "100000"},
    )
    run_response = client.post(
        "/workflows/paper/runs/ma-cross",
        json={
            "account_id": account_response.json()["account_id"],
            "symbol": "000001",
            "short_window": 3,
            "long_window": 8,
            "order_size": 50,
        },
    )
    client.post(f"/workflows/paper/runs/{run_response.json()['run_id']}/tick")

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "000001" in html
    assert "Dashboard Paper" in html
    assert f"#{backtest_response.json()['run_id']}" in html
    assert f"#{run_response.json()['run_id']}" in html
    assert "running" in html


def test_dashboard_form_actions_complete_core_workflow(legacy_sqlite_db: Path):
    client, engine = make_client()

    import_response = client.post(
        "/dashboard/actions/import-legacy",
        data={"legacy_db_path": str(legacy_sqlite_db)},
        follow_redirects=False,
    )
    backtest_response = client.post(
        "/dashboard/actions/backtests/ma-cross",
        data={
            "symbol": "000001",
            "short_window": "3",
            "long_window": "8",
            "order_size": "50",
            "initial_cash": "100000",
        },
        follow_redirects=False,
    )
    account_response = client.post(
        "/dashboard/actions/paper/accounts",
        data={"name": "Form Paper", "initial_cash": "100000"},
        follow_redirects=False,
    )
    with session_scope(engine) as session:
        account_id = session.scalar(
            select(PaperAccountORM.id).where(PaperAccountORM.name == "Form Paper")
        )
    run_response = client.post(
        "/dashboard/actions/paper/runs/ma-cross",
        data={
            "account_id": str(account_id),
            "symbol": "000001",
            "short_window": "3",
            "long_window": "8",
            "order_size": "50",
            "max_order_value": "100000",
        },
        follow_redirects=False,
    )
    with session_scope(engine) as session:
        run_id = session.scalar(
            select(PaperRunORM.id).where(PaperRunORM.account_id == account_id)
        )
    tick_response = client.post(
        "/dashboard/actions/paper/tick",
        data={"run_id": str(run_id)},
        follow_redirects=False,
    )

    assert import_response.status_code == 303
    assert backtest_response.status_code == 303
    assert account_response.status_code == 303
    assert run_response.status_code == 303
    assert tick_response.status_code == 303

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Form Paper" in html
    assert "000001" in html
    assert "Paper Runs" in html
    assert "Snapshots" in html
    assert f"#{run_id}" in html


def test_dashboard_account_form_error_displays_plain_message():
    client, _ = make_client()

    response = client.post(
        "/dashboard/actions/paper/accounts",
        data={"name": "   ", "initial_cash": "100000"},
    )

    assert response.status_code == 400
    assert "name is required" in response.text


def test_dashboard_backtest_action_rejects_symbol_without_market_bars(
    legacy_sqlite_db: Path,
):
    client, _ = make_client()
    import_response = client.post(
        "/workflows/import-legacy",
        json={"legacy_db_path": str(legacy_sqlite_db)},
    )

    response = client.post(
        "/dashboard/actions/backtests/ma-cross",
        data={
            "symbol": "NO_SUCH",
            "short_window": "3",
            "long_window": "8",
            "order_size": "50",
            "initial_cash": "100000",
        },
    )

    assert import_response.status_code == 200
    assert response.status_code == 400
    assert "no market bars found" in response.text


def test_dashboard_displays_workflow_run_history(legacy_sqlite_db: Path):
    client, _ = make_client()
    client.post("/workflows/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Workflow Runs" in html
    assert "import_legacy" in html
    assert "succeeded" in html
    assert "Environment" in html
    assert "Auth" in html


def test_dashboard_displays_job_runs(legacy_sqlite_db: Path):
    client, _ = make_client()
    response = client.post(
        "/jobs/import-legacy",
        json={"legacy_db_path": str(legacy_sqlite_db)},
    )

    dashboard = client.get("/dashboard")

    assert response.status_code == 200
    assert dashboard.status_code == 200
    html = dashboard.text
    assert "Job Runs" in html
    assert "import_legacy" in html
    assert "100%" in html
    assert "succeeded" in html


def test_dashboard_displays_data_sync_runs():
    from datetime import UTC, datetime

    from quant_trading.storage.repositories import DataSyncRunRepository

    client, engine = make_client()
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        repo = DataSyncRunRepository(session)
        row = repo.create_running(
            "akshare", "000001", "a_stock", "stock", "CNY", "SZSE", None, None, 1, now
        )
        repo.mark_succeeded(row, imported_bars=10, finished_at=now, duration_ms=20)

    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Data Sync Runs" in html
    assert "akshare" in html
    assert "000001" in html
    assert "10" in html
    assert "succeeded" in html


def test_dashboard_displays_job_schedules_and_events():
    from datetime import UTC, datetime

    from quant_trading.jobs.runtime import MARKET_DATA_SYNC, job_payload_dumps
    from quant_trading.storage.repositories import (
        JobEventRepository,
        JobRunRepository,
        JobScheduleRepository,
    )

    client, engine = make_client()
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(engine) as session:
        job = JobRunRepository(session).create_queued(
            MARKET_DATA_SYNC,
            job_payload_dumps({"provider": "fake", "symbol": "000001"}),
            now,
        )
        JobEventRepository(session).record(
            job.id,
            "queued",
            "job queued",
            progress=0,
            created_at=now,
        )
        JobScheduleRepository(session).create(
            "daily-000001-sync",
            MARKET_DATA_SYNC,
            job_payload_dumps({"provider": "fake", "symbol": "000001"}),
            "interval",
            86400,
            True,
            now,
            now,
        )

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Job Schedules" in response.text
    assert "daily-000001-sync" in response.text
    assert "Job Events" in response.text
    assert "job queued" in response.text


def test_dashboard_displays_schedule_lease_state():
    from datetime import datetime, timedelta

    from quant_trading.jobs.runtime import MARKET_DATA_SYNC
    from quant_trading.storage.repositories import JobScheduleRepository

    client, engine = make_client()
    now = datetime(2026, 6, 23, 9, 30)
    with session_scope(engine) as session:
        schedule = JobScheduleRepository(session).create(
            name="leased-dashboard-sync",
            job_type=MARKET_DATA_SYNC,
            request_payload="{}",
            schedule_type="interval",
            interval_seconds=3600,
            enabled=True,
            next_run_at=now,
            created_at=now,
        )
        schedule.locked_until = now + timedelta(minutes=5)
        schedule.locked_by = "dashboard-runner"
        schedule.lock_acquired_at = now
        session.flush()

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "dashboard-runner" in response.text
    assert "Lease" in response.text


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
    assert "new EventSource" in html
    assert 'id="job-events-body"' in html


def test_dashboard_omits_job_event_stream_hook_without_active_job():
    client, _ = make_client()

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "data-job-stream-url" not in response.text


def test_failed_dashboard_action_creates_visible_failed_workflow_run(
    legacy_sqlite_db: Path,
):
    client, _ = make_client()
    client.post("/workflows/import-legacy", json={"legacy_db_path": str(legacy_sqlite_db)})

    response = client.post(
        "/dashboard/actions/backtests/ma-cross",
        data={
            "symbol": "NO_SUCH",
            "short_window": "3",
            "long_window": "8",
            "order_size": "50",
            "initial_cash": "100000",
        },
    )

    assert response.status_code == 400
    assert "no market bars found" in response.text
    assert "Workflow Runs" in response.text
    assert "backtest_ma_cross" in response.text
    assert "failed" in response.text
