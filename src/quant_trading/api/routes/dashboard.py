from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
import json
from typing import Any, TypeVar
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import (
    BacktestRunORM,
    CashLedgerORM,
    DataSyncRunORM,
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    InstrumentORM,
    JobEventORM,
    JobRunORM,
    JobScheduleORM,
    KillSwitchEventORM,
    MarketBarORM,
    OperatorApprovalRequestORM,
    PaperAccountORM,
    PaperFillORM,
    PaperOrderORM,
    PaperPositionORM,
    PaperRunORM,
    PortfolioSnapshotORM,
    RiskDecisionORM,
    SafetyIncidentORM,
    WorkflowRunORM,
)
from quant_trading.storage.repositories import (
    DataSyncRunRepository,
    JobEventRepository,
    JobRunRepository,
    JobScheduleRepository,
    WorkflowRunRepository,
)
from quant_trading.workflows.operations import (
    create_paper_account,
    import_legacy_data,
    run_ma_cross_backtest,
    run_paper_tick,
    start_ma_cross_paper_run,
)
from quant_trading.operations.readiness import build_operations_readiness
from quant_trading.workflows.runner import WorkflowCommandRunner

router = APIRouter(tags=["dashboard"])
T = TypeVar("T")
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


@router.get("/dashboard", response_class=HTMLResponse)
def show_dashboard(request: Request) -> HTMLResponse:
    return _dashboard_response(request)


@router.post("/dashboard/actions/import-legacy", response_model=None)
async def dashboard_import_legacy(request: Request) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    return _run_dashboard_action(
        request,
        "import_legacy",
        {"legacy_db_path": str(form.get("legacy_db_path", ""))},
        lambda: import_legacy_data(
            request.app.state.engine,
            str(form.get("legacy_db_path", "")),
        ),
        "Legacy data imported",
    )


@router.post("/dashboard/actions/backtests/ma-cross", response_model=None)
async def dashboard_run_backtest(request: Request) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    return _run_dashboard_action(
        request,
        "backtest_ma_cross",
        {
            "symbol": str(form.get("symbol", "")),
            "short_window": str(form.get("short_window", "")),
            "long_window": str(form.get("long_window", "")),
            "order_size": str(form.get("order_size", "")),
            "initial_cash": str(form.get("initial_cash", "")),
        },
        lambda: run_ma_cross_backtest(
            request.app.state.engine,
            symbol=str(form.get("symbol", "")),
            short_window=int(str(form.get("short_window", ""))),
            long_window=int(str(form.get("long_window", ""))),
            order_size=int(str(form.get("order_size", ""))),
            initial_cash=Decimal(str(form.get("initial_cash", ""))),
        ),
        "Backtest started",
    )


@router.post("/dashboard/actions/paper/accounts", response_model=None)
async def dashboard_create_account(request: Request) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    name = str(form.get("name", "")).strip()
    return _run_dashboard_action(
        request,
        "paper_create_account",
        {
            "name": name,
            "initial_cash": str(form.get("initial_cash", "")),
            "base_currency": str(form.get("base_currency", "CNY")),
        },
        lambda: create_paper_account(
            request.app.state.engine,
            name=name,
            initial_cash=Decimal(str(form.get("initial_cash", ""))),
            base_currency=str(form.get("base_currency", "CNY")),
        ),
        "Paper account created",
    )


@router.post("/dashboard/actions/paper/runs/ma-cross", response_model=None)
async def dashboard_create_paper_run(request: Request) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    return _run_dashboard_action(
        request,
        "paper_start_ma_cross_run",
        {
            "account_id": str(form.get("account_id", "")),
            "symbol": str(form.get("symbol", "")),
            "short_window": str(form.get("short_window", "")),
            "long_window": str(form.get("long_window", "")),
            "order_size": str(form.get("order_size", "")),
            "max_order_value": str(form.get("max_order_value", "100000")),
        },
        lambda: start_ma_cross_paper_run(
            request.app.state.engine,
            account_id=int(str(form.get("account_id", ""))),
            symbol=str(form.get("symbol", "")),
            short_window=int(str(form.get("short_window", ""))),
            long_window=int(str(form.get("long_window", ""))),
            order_size=int(str(form.get("order_size", ""))),
            max_order_value=Decimal(str(form.get("max_order_value", "100000"))),
        ),
        "Paper run created",
    )


@router.post("/dashboard/actions/paper/tick", response_model=None)
async def dashboard_run_tick(request: Request) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    return _run_dashboard_action(
        request,
        "paper_run_tick",
        {"run_id": str(form.get("run_id", ""))},
        lambda: run_paper_tick(
            request.app.state.engine,
            int(str(form.get("run_id", ""))),
        ),
        "Paper tick processed",
    )


def _run_dashboard_action(
    request: Request,
    command_name: str,
    request_payload: dict[str, Any],
    callback: Callable[[], T],
    notice: str,
) -> HTMLResponse | RedirectResponse:
    try:
        WorkflowCommandRunner(request.app.state.engine).run(
            command_name,
            request_payload,
            callback,
        )
    except Exception as exc:
        return _dashboard_response(request, error=str(exc), status_code=400)
    return RedirectResponse(f"/dashboard?notice={quote(notice)}", status_code=303)


def _dashboard_response(
    request: Request,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    state = _collect_state(request)
    notice = request.query_params.get("notice")
    return HTMLResponse(
        _render_dashboard(state, notice=notice, error=error),
        status_code=status_code,
    )


def _collect_state(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    settings = request.app.state.settings
    with session_scope(engine) as session:
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
        return {
            "db_label": engine.url.render_as_string(hide_password=True),
            "app_env": settings.app_env,
            "auth_enabled": settings.require_auth,
            "operations_readiness": build_operations_readiness(
                session,
                settings,
                _now(),
            ),
            "execution_order_decisions": _latest(session, ExecutionOrderDecisionORM),
            "execution_order_intents": _latest(session, ExecutionOrderIntentORM),
            "approval_requests": _latest(session, OperatorApprovalRequestORM),
            "safety_incidents": _latest(session, SafetyIncidentORM),
            "kill_switch_events": _latest(session, KillSwitchEventORM),
            "instrument_count": session.scalar(select(func.count(InstrumentORM.id))) or 0,
            "latest_bar": session.scalar(select(func.max(MarketBarORM.timestamp))),
            "workflow_runs": WorkflowRunRepository(session).list_recent(limit=20),
            "job_runs": job_runs,
            "job_schedules": JobScheduleRepository(session).list_recent(limit=20),
            "job_events": job_events,
            "active_job": active_job,
            "active_job_latest_event_id": active_job_latest_event_id,
            "data_sync_runs": DataSyncRunRepository(session).list_recent(limit=20),
            "backtests": _latest(session, BacktestRunORM),
            "accounts": _latest(session, PaperAccountORM),
            "runs": _latest(session, PaperRunORM),
            "positions": _latest(session, PaperPositionORM),
            "orders": _latest(session, PaperOrderORM),
            "fills": _latest(session, PaperFillORM),
            "risk_decisions": _latest(session, RiskDecisionORM),
            "ledger": _latest(session, CashLedgerORM),
            "snapshots": _latest(session, PortfolioSnapshotORM),
        }


def _latest(session: Session, model: type[T], limit: int = 10) -> list[T]:
    return list(
        session.scalars(select(model).order_by(model.id.desc()).limit(limit)).all()
    )


def _active_job(rows: list[JobRunORM]) -> JobRunORM | None:
    for row in rows:
        if row.status not in TERMINAL_JOB_STATUSES:
            return row
    return None


def _render_dashboard(
    state: dict[str, Any],
    notice: str | None,
    error: str | None,
) -> str:
    notice_html = (
        f'<div class="notice">{_e(notice)}</div>'
        if notice
        else ""
    )
    error_html = f'<div class="error">{_e(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Operations Workbench</title>
  <style>
    body {{ margin: 0; font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1d2430; background: #f6f7f9; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 20px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    h2 {{ margin: 20px 0 8px; font-size: 16px; }}
    .meta {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 12px 0; }}
    .metric {{ border: 1px solid #ccd2dc; background: #fff; padding: 8px; border-radius: 6px; }}
    .metric span {{ display: block; color: #647084; font-size: 11px; text-transform: uppercase; }}
    .forms {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }}
    form {{ display: grid; grid-template-columns: 1fr; gap: 6px; border: 1px solid #ccd2dc; background: #fff; padding: 10px; border-radius: 6px; }}
    form h2 {{ margin: 0 0 2px; font-size: 13px; }}
    input {{ min-width: 0; padding: 6px 7px; border: 1px solid #b8c0cc; border-radius: 4px; background: #fff; }}
    button {{ padding: 7px 9px; border: 1px solid #253248; border-radius: 4px; background: #253248; color: #fff; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #ccd2dc; }}
    th, td {{ padding: 6px 8px; border-bottom: 1px solid #e2e6ec; text-align: left; vertical-align: top; }}
    th {{ font-size: 11px; color: #647084; text-transform: uppercase; background: #eef1f5; }}
    .notice {{ margin: 10px 0; padding: 8px; background: #eaf7ee; border: 1px solid #9dd6ad; }}
    .error {{ margin: 10px 0; padding: 8px; background: #fff0f0; border: 1px solid #dc9a9a; color: #8a1f1f; }}
    .empty {{ color: #647084; }}
    .status-failed {{ color: #8a1f1f; font-weight: 600; }}
  </style>
</head>
<body>
<main{_job_stream_attrs(state)}>
  <h1>Operations Workbench</h1>
  {notice_html}
  {error_html}
  <section class="meta">
    <div class="metric"><span>Database</span>{_e(state["db_label"])}</div>
    <div class="metric"><span>Environment</span>{_e(state["app_env"])}</div>
    <div class="metric"><span>Auth</span>{_e("enabled" if state["auth_enabled"] else "disabled")}</div>
    <div class="metric"><span>Instruments</span>{_e(state["instrument_count"])}</div>
    <div class="metric"><span>Latest Imported Bar</span>{_e(state["latest_bar"] or "none")}</div>
  </section>
  {_operations_safety_section(state)}
  <section class="forms" aria-label="Dashboard actions">
    {_render_forms(state)}
  </section>
  {_workflow_runs_table(state)}
  {_job_runs_table(state)}
  {_job_schedules_table(state)}
  {_job_events_table(state)}
  {_data_sync_runs_table(state)}
  {_table("Backtest Runs", ["ID", "Strategy", "Symbol", "Initial Cash", "Final Equity", "Status"], state["backtests"], lambda r: [f"#{r.id}", r.strategy_name, r.symbol, r.initial_cash, r.final_equity, r.status])}
  {_table("Paper Accounts", ["ID", "Name", "Currency", "Initial Cash", "Status", "Created"], state["accounts"], lambda r: [f"#{r.id}", r.name, r.base_currency, r.initial_cash, r.status, r.created_at])}
  {_table("Paper Runs", ["ID", "Account", "Strategy", "Symbol", "Status", "Last Processed"], state["runs"], lambda r: [f"#{r.id}", f"#{r.account_id}", r.strategy_name, r.symbol, r.status, r.last_processed_at])}
  {_table("Latest Positions", ["ID", "Account", "Symbol", "Qty", "Avg Cost", "Market Price"], state["positions"], lambda r: [f"#{r.id}", f"#{r.account_id}", r.symbol, r.quantity, r.avg_cost, r.market_price])}
  {_table("Orders", ["ID", "Run", "Symbol", "Side", "Qty", "Status", "Risk"], state["orders"], lambda r: [f"#{r.id}", f"#{r.run_id}", r.symbol, r.side, r.quantity, r.status, r.risk_decision])}
  {_table("Fills", ["ID", "Run", "Order", "Symbol", "Side", "Qty", "Price"], state["fills"], lambda r: [f"#{r.id}", f"#{r.run_id}", f"#{r.order_id}", r.symbol, r.side, r.quantity, r.price])}
  {_table("Risk Decisions", ["ID", "Run", "Order", "Decision", "Rule", "Message"], state["risk_decisions"], lambda r: [f"#{r.id}", f"#{r.run_id}" if r.run_id else "", f"#{r.order_id}" if r.order_id else "", r.decision, r.rule_name, r.message])}
  {_table("Cash Ledger Rows", ["ID", "Account", "Run", "Event", "Amount", "Cash After", "Date"], state["ledger"], lambda r: [f"#{r.id}", f"#{r.account_id}", f"#{r.run_id}" if r.run_id else "", r.event_type, r.amount, r.cash_after, r.occurred_at])}
  {_table("Snapshots", ["ID", "Account", "Run", "Date", "Equity", "Cash", "Drawdown"], state["snapshots"], lambda r: [f"#{r.id}", f"#{r.account_id}", f"#{r.run_id}" if r.run_id else "", r.timestamp, r.equity, r.cash, r.drawdown])}
  {_job_event_stream_script(state)}
</main>
</body>
</html>"""


def _operations_safety_section(state: dict[str, Any]) -> str:
    readiness = state["operations_readiness"]
    kill_switch = "active" if readiness["global_kill_switch_active"] else "inactive"
    open_incidents = (
        readiness["open_critical_incidents"] + readiness["open_warning_incidents"]
    )
    safety_state = readiness.get("safety_state") or {}
    decisions = _table(
        "Recent Safety Decisions",
        ["ID", "Intent", "Decision", "Reason", "Message", "Created"],
        state["execution_order_decisions"],
        lambda r: [
            f"#{r.id}",
            f"#{r.order_intent_id}",
            r.decision_type,
            r.reason_code,
            r.message,
            r.created_at,
        ],
    )
    intents = _table(
        "Recent Order Intents",
        ["ID", "Client Order", "Symbol", "Side", "Qty", "Mode", "Status", "Approval", "Blocked"],
        state["execution_order_intents"],
        lambda r: [
            f"#{r.id}",
            r.client_order_id,
            r.symbol,
            r.side,
            r.quantity,
            r.broker_mode,
            r.status,
            f"#{r.approval_request_id}" if r.approval_request_id else "",
            r.blocked_reason_code or "",
        ],
    )
    approvals = _table(
        "Recent Approval Requests",
        ["ID", "Resource", "Status", "Reason", "Requested By", "Requested", "Decided By"],
        state["approval_requests"],
        lambda r: [
            f"#{r.id}",
            f"{r.resource_type} #{r.resource_id}",
            r.status,
            r.reason_code,
            r.requested_by,
            r.requested_at,
            r.decided_by or "",
        ],
    )
    incidents = _table(
        "Recent Safety Incidents",
        ["ID", "Severity", "Category", "Status", "Reason", "Message", "Created"],
        state["safety_incidents"],
        lambda r: [
            f"#{r.id}",
            r.severity,
            r.category,
            r.status,
            r.reason_code,
            r.message,
            r.created_at,
        ],
    )
    kill_switch_events = _table(
        "Recent Kill Switch Events",
        ["ID", "Scope", "State", "Operator", "Reason", "Created"],
        state["kill_switch_events"],
        lambda r: [
            f"#{r.id}",
            r.scope,
            _kill_switch_event_state(r),
            r.operator,
            r.reason,
            r.created_at,
        ],
    )
    return f"""
  <section aria-label="Operations Safety">
    <h2>Operations Safety</h2>
    <div class="meta">
      {_metric("Kill Switch", kill_switch)}
      {_metric("Safe For Simulated", _bool_text(readiness["safe_for_simulated_paper"]))}
      {_metric("Safe For Dry Run", _bool_text(readiness["safe_for_dry_run"]))}
      {_metric("Safe For Live", _bool_text(readiness["safe_for_live"]))}
      {_metric("Pending Approvals", readiness["pending_approval_requests"])}
      {_metric("Open Incidents", open_incidents)}
      {_metric("Safety Reason", safety_state.get("reason") or "")}
      {_metric("Readiness Reasons", ", ".join(readiness["reasons"]))}
    </div>
    {decisions}
    {intents}
    {approvals}
    {incidents}
    {kill_switch_events}
  </section>
  """


def _metric(label: str, value: Any) -> str:
    return (
        f'<div class="metric" aria-label="{_e(label)} {_e(value)}">'
        f"<span>{_e(label)}</span>{_e(value)}</div>"
    )


def _bool_text(value: Any) -> str:
    return "true" if value else "false"


def _render_forms(state: dict[str, Any]) -> str:
    first_account_id = state["accounts"][0].id if state["accounts"] else ""
    first_run_id = state["runs"][0].id if state["runs"] else ""
    return f"""
    <form method="post" action="/dashboard/actions/import-legacy">
      <h2>Import Legacy Data</h2>
      <input name="legacy_db_path" placeholder="legacy SQLite path" required>
      <button type="submit">Import</button>
    </form>
    <form method="post" action="/dashboard/actions/backtests/ma-cross">
      <h2>Run MA Cross Backtest</h2>
      <input name="symbol" value="000001" required>
      <input name="short_window" value="3" type="number" min="1" required>
      <input name="long_window" value="8" type="number" min="1" required>
      <input name="order_size" value="50" type="number" min="1" required>
      <input name="initial_cash" value="100000" required>
      <button type="submit">Run Backtest</button>
    </form>
    <form method="post" action="/dashboard/actions/paper/accounts">
      <h2>Create Paper Account</h2>
      <input name="name" placeholder="account name" required>
      <input name="initial_cash" value="100000" required>
      <input name="base_currency" value="CNY" required>
      <button type="submit">Create Account</button>
    </form>
    <form method="post" action="/dashboard/actions/paper/runs/ma-cross">
      <h2>Create MA Cross Paper Run</h2>
      <input name="account_id" value="{_e(first_account_id)}" placeholder="account id" type="number" min="1" required>
      <input name="symbol" value="000001" required>
      <input name="short_window" value="3" type="number" min="1" required>
      <input name="long_window" value="8" type="number" min="1" required>
      <input name="order_size" value="50" type="number" min="1" required>
      <input name="max_order_value" value="100000" required>
      <button type="submit">Create Run</button>
    </form>
    <form method="post" action="/dashboard/actions/paper/tick">
      <h2>Run One Paper Tick</h2>
      <input name="run_id" value="{_e(first_run_id)}" placeholder="run id" type="number" min="1" required>
      <button type="submit">Run Tick</button>
    </form>
    """


def _workflow_runs_table(state: dict[str, Any]) -> str:
    return _table(
        "Workflow Runs",
        ["ID", "Command", "Status", "Started", "Duration", "Created Object", "Error"],
        state["workflow_runs"],
        lambda r: [
            f"#{r.id}",
            r.command_name,
            r.status,
            r.started_at,
            f"{r.duration_ms} ms" if r.duration_ms is not None else "",
            _object_ref(r),
            r.error_message or "",
        ],
    )


def _job_runs_table(state: dict[str, Any]) -> str:
    return _table(
        "Job Runs",
        ["ID", "Type", "Status", "Progress", "Started", "Duration", "Workflow Run", "Error"],
        state["job_runs"],
        lambda r: [
            f"#{r.id}",
            r.job_type,
            r.status,
            f"{r.progress}%",
            r.started_at,
            f"{r.duration_ms} ms" if r.duration_ms is not None else "",
            f"#{r.workflow_run_id}" if r.workflow_run_id else "",
            r.error_message or "",
        ],
    )


def _data_sync_runs_table(state: dict[str, Any]) -> str:
    return _table(
        "Data Sync Runs",
        ["ID", "Provider", "Symbol", "Status", "Bars", "Range", "Job", "Duration", "Error"],
        state["data_sync_runs"],
        lambda r: [
            f"#{r.id}",
            r.provider,
            r.symbol,
            r.status,
            r.imported_bars,
            _date_range(r),
            f"#{r.job_run_id}" if r.job_run_id else "",
            f"{r.duration_ms} ms" if r.duration_ms is not None else "",
            r.error_message or "",
        ],
    )


def _job_schedules_table(state: dict[str, Any]) -> str:
    return _table(
        "Job Schedules",
        [
            "ID",
            "Name",
            "Type",
            "Enabled",
            "Interval",
            "Next Run",
            "Last Run",
            "Last Job",
            "Lease",
        ],
        state["job_schedules"],
        lambda r: [
            f"#{r.id}",
            r.name,
            r.job_type,
            "yes" if r.enabled else "no",
            f"{r.interval_seconds}s",
            r.next_run_at,
            r.last_run_at or "",
            f"#{r.last_job_run_id}" if r.last_job_run_id else "",
            _format_schedule_lease(r),
        ],
    )


def _format_schedule_lease(row: JobScheduleORM) -> str:
    if row.locked_until is None:
        return ""
    owner = row.locked_by or "unknown"
    return f"{owner} until {row.locked_until}"


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


def _date_range(row: DataSyncRunORM) -> str:
    if row.start_date and row.end_date:
        return f"{row.start_date} to {row.end_date}"
    if row.start_date:
        return f"from {row.start_date}"
    if row.end_date:
        return f"through {row.end_date}"
    return ""


def _table(
    title: str,
    columns: list[str],
    rows: list[Any],
    row_values: Callable[[Any], list[Any]],
) -> str:
    head = "".join(f"<th>{_e(column)}</th>" for column in columns)
    if not rows:
        body = (
            f'<tr><td class="empty" colspan="{len(columns)}">No rows</td></tr>'
        )
    else:
        body = "".join(
            "<tr>"
            + "".join(_table_cell(value) for value in row_values(row))
            + "</tr>"
            for row in rows
        )
    return f"<section><h2>{_e(title)}</h2><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section>"


def _table_cell(value: Any) -> str:
    cell_class = ' class="status-failed"' if value == "failed" else ""
    return f"<td{cell_class}>{_e(value)}</td>"


def _object_ref(row: WorkflowRunORM | JobRunORM) -> str:
    if not row.created_object_type or row.created_object_id is None:
        return ""
    return f"{row.created_object_type} #{row.created_object_id}"


def _kill_switch_event_state(row: KillSwitchEventORM) -> str:
    payload = _json_loads(row.new_state_payload)
    active = payload.get("kill_switch_active")
    if active is True:
        return "active"
    if active is False:
        return "inactive"
    return ""


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _e(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)
