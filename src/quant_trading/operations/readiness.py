from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_trading.config import AppSettings
from quant_trading.storage.models import (
    DataQualityReportORM,
    DataSyncRunORM,
    JobRunORM,
    OperatorApprovalRequestORM,
    ResearchValidationReportORM,
    SafetyIncidentORM,
)
from quant_trading.storage.repositories import (
    ExecutionSafetyStateRepository,
)


def build_operations_readiness(
    session: Session,
    settings: AppSettings,
    now: datetime,
) -> dict[str, Any]:
    safety_repo = ExecutionSafetyStateRepository(session)
    safety_state = safety_repo.get_or_create_global(now)
    open_critical_incidents = _count_open_incidents(session, "critical")
    open_warning_incidents = _count_open_incidents(session, "warning")
    pending_approvals = _count_pending_approvals(session)
    stuck_jobs = _count_stuck_jobs(session, now)
    failed_jobs_24h = _count_failed_jobs_24h(session, now)
    stale_data_reports = _count_stale_data_reports(session)
    latest_data_sync = _latest_data_sync(session)
    latest_research_validation = _latest_research_validation(session)

    reasons = ["live_execution_unavailable"]
    if safety_state.kill_switch_active:
        reasons.append("global_kill_switch_active")
    if open_critical_incidents:
        reasons.append("open_critical_incidents")
    if open_warning_incidents:
        reasons.append("open_warning_incidents")
    if pending_approvals:
        reasons.append("pending_operator_approvals")

    pre_live_safe = (
        not safety_state.kill_switch_active
        and open_critical_incidents == 0
        and open_warning_incidents == 0
        and pending_approvals == 0
    )

    return {
        "environment": settings.app_env,
        "trading_enabled": settings.trading_enabled,
        "broker_mode": settings.broker_mode,
        "global_kill_switch_active": safety_state.kill_switch_active,
        "safety_state": safety_repo.payload(safety_state),
        "live_execution_available": False,
        "safe_for_simulated_paper": pre_live_safe and safety_state.simulated_enabled,
        "safe_for_dry_run": pre_live_safe and safety_state.dry_run_enabled,
        "safe_for_live": False,
        "reasons": reasons,
        "open_critical_incidents": open_critical_incidents,
        "open_warning_incidents": open_warning_incidents,
        "pending_approval_requests": pending_approvals,
        "latest_data_sync_status": (
            latest_data_sync["status"] if latest_data_sync is not None else None
        ),
        "latest_research_validation_status": (
            latest_research_validation["validation_status"]
            if latest_research_validation is not None
            else None
        ),
        "open_incidents": {
            "critical": open_critical_incidents,
            "warning": open_warning_incidents,
        },
        "pending_approvals": pending_approvals,
        "stuck_jobs": stuck_jobs,
        "failed_jobs_24h": failed_jobs_24h,
        "stale_data_reports": stale_data_reports,
        "latest_data_sync": latest_data_sync,
        "latest_research_validation": latest_research_validation,
        "generated_at": now.isoformat(),
    }


def _count_open_incidents(session: Session, severity: str) -> int:
    return session.scalar(
        select(func.count(SafetyIncidentORM.id)).where(
            SafetyIncidentORM.status != "resolved",
            SafetyIncidentORM.severity == severity,
        )
    ) or 0


def _count_pending_approvals(session: Session) -> int:
    return session.scalar(
        select(func.count(OperatorApprovalRequestORM.id)).where(
            OperatorApprovalRequestORM.status == "pending",
        )
    ) or 0


def _count_stuck_jobs(session: Session, now: datetime) -> int:
    threshold = now - timedelta(hours=1)
    return session.scalar(
        select(func.count(JobRunORM.id)).where(
            JobRunORM.status.in_(("queued", "running")),
            JobRunORM.updated_at <= threshold,
        )
    ) or 0


def _count_failed_jobs_24h(session: Session, now: datetime) -> int:
    threshold = now - timedelta(hours=24)
    return session.scalar(
        select(func.count(JobRunORM.id)).where(
            JobRunORM.status == "failed",
            JobRunORM.finished_at >= threshold,
        )
    ) or 0


def _count_stale_data_reports(session: Session) -> int:
    return session.scalar(
        select(func.count(DataQualityReportORM.id)).where(
            DataQualityReportORM.stale_data.is_(True),
            DataQualityReportORM.status != "failed",
        )
    ) or 0


def _latest_data_sync(session: Session) -> dict[str, Any] | None:
    row = session.scalar(
        select(DataSyncRunORM).order_by(
            DataSyncRunORM.created_at.desc(),
            DataSyncRunORM.id.desc(),
        )
    )
    if row is None:
        return None
    return {
        "id": row.id,
        "provider": row.provider,
        "symbol": row.symbol,
        "status": row.status,
        "imported_bars": row.imported_bars,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "created_at": _iso(row.created_at),
    }


def _latest_research_validation(session: Session) -> dict[str, Any] | None:
    row = session.scalar(
        select(ResearchValidationReportORM).order_by(
            ResearchValidationReportORM.created_at.desc(),
            ResearchValidationReportORM.id.desc(),
        )
    )
    if row is None:
        return None
    return {
        "id": row.id,
        "candidate_review_id": row.candidate_review_id,
        "symbol": row.symbol,
        "strategy_name": row.strategy_name,
        "validation_status": row.validation_status,
        "readiness_floor": row.readiness_floor,
        "created_at": _iso(row.created_at),
    }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
