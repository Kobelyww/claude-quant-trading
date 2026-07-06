from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from typing import Any

from sqlalchemy import Engine

from quant_trading.agents.output_safety import contains_unsafe_agent_text
from quant_trading.security import sanitize_error_message
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import AgentLearningMemoryORM
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentLearningMemoryRepository,
    ResearchValidationReportRepository,
    SafetyIncidentRepository,
)


class LearningMemoryError(ValueError):
    pass


class LearningMemoryNotFoundError(LearningMemoryError):
    pass


DEFAULT_SYMBOL_MEMORY_EXPIRY_DAYS = 180
MIN_PROMPT_MEMORY_CONFIDENCE = Decimal("0.4")


@dataclass(frozen=True)
class MemoryPayload:
    id: int
    memory_type: str
    scope: str
    symbol: str | None
    strategy_skill_id: int | None
    title: str
    content: str
    reason_code: str
    confidence: Decimal
    importance: Decimal
    source_type: str
    source_id: int


class LearningMemoryService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create_manual_memory(
        self,
        memory_type: str,
        scope: str,
        title: str,
        content: str,
        reason_code: str,
        operator: str,
        symbol: str | None = None,
        strategy_skill_id: int | None = None,
        source_type: str = "operator_approval_request",
        source_id: int = 0,
        evidence_payload: dict[str, Any] | None = None,
        confidence: Decimal = Decimal("1"),
        importance: Decimal = Decimal("0.5"),
        expires_at: datetime | None = None,
    ) -> MemoryPayload:
        return self._create_memory(
            memory_type=memory_type,
            scope=scope,
            title=title,
            content=content,
            reason_code=reason_code,
            source_type=source_type,
            source_id=source_id,
            evidence_payload=evidence_payload or {"operator": operator},
            confidence=confidence,
            importance=importance,
            created_by=operator,
            symbol=symbol,
            strategy_skill_id=strategy_skill_id,
            expires_at=expires_at,
        )

    def extract_from_candidate_review(
        self,
        candidate_review_id: int,
    ) -> list[MemoryPayload]:
        with session_scope(self.engine) as session:
            review = AgentCandidateReviewRepository(session).get(candidate_review_id)
            if review is None:
                raise LearningMemoryNotFoundError("candidate review not found")
            if review.status != "rejected":
                return []

            title = f"Rejected candidate: {review.strategy_name} {review.symbol}".strip()
            note = _safe_fragment(review.operator_note)
            content = (
                "Operator rejected this research candidate. "
                "Require additional deterministic validation before reconsidering similar ideas."
            )
            if note:
                content = f"{content} Operator note: {note}"
            _ensure_safe_memory_text(title, content)
            now = _utcnow()
            scope = "symbol" if review.symbol else "global"
            row, _ = AgentLearningMemoryRepository(session).get_or_create_active(
                memory_type="operator_decision",
                scope=scope,
                source_type="candidate_review",
                source_id=review.id,
                reason_code="candidate_rejected",
                title=title,
                content=content,
                evidence_payload={
                    "candidate_review_id": review.id,
                    "operator": review.operator,
                    "status": review.status,
                    "strategy_name": review.strategy_name,
                    "symbol": review.symbol,
                },
                confidence=Decimal("1"),
                importance=Decimal("0.8"),
                now=now,
                symbol=review.symbol,
                expires_at=_default_expires_at(scope, now, None),
                created_by="system",
            )
            return [_to_payload(row)]

    def extract_from_validation_report(self, report_id: int) -> list[MemoryPayload]:
        with session_scope(self.engine) as session:
            report = ResearchValidationReportRepository(session).get(report_id)
            if report is None:
                raise LearningMemoryNotFoundError("research validation report not found")

            summary = _json_loads(report.summary_payload)
            validation_status = str(report.validation_status or "").strip().lower()
            if validation_status == "passed":
                memory_type = "strategy_success"
                reason_code = "research_validation_passed"
                importance = Decimal("0.5")
                confidence = Decimal("0.7")
                title = (
                    f"Validation passed: {report.strategy_name} {report.symbol}".strip()
                )
                content = (
                    f"Research validation passed for {report.strategy_name} on "
                    f"{report.symbol}. Use only as conservative research context."
                )
            elif validation_status in {"failed", "needs_review"}:
                memory_type = "strategy_failure"
                reason_code = _first_summary_reason_code(summary)
                importance = Decimal("0.7")
                confidence = Decimal("0.9")
                title = (
                    f"Validation did not pass: {report.strategy_name} "
                    f"{report.symbol}".strip()
                )
                content = (
                    f"Research validation did not pass for {report.strategy_name} on "
                    f"{report.symbol}. Readiness floor: {report.readiness_floor}. "
                    f"Reason: {reason_code}."
                )
            else:
                return []

            _ensure_safe_memory_text(title, content)
            now = _utcnow()
            scope = "symbol" if report.symbol else "global"
            row, _ = AgentLearningMemoryRepository(session).get_or_create_active(
                memory_type=memory_type,
                scope=scope,
                source_type="research_validation_report",
                source_id=report.id,
                reason_code=reason_code,
                title=title,
                content=content,
                evidence_payload={
                    "research_validation_report_id": report.id,
                    "candidate_review_id": report.candidate_review_id,
                    "source_backtest_run_id": report.source_backtest_run_id,
                    "validation_status": report.validation_status,
                    "readiness_floor": report.readiness_floor,
                    "summary": summary,
                },
                confidence=confidence,
                importance=importance,
                now=now,
                symbol=report.symbol,
                expires_at=_default_expires_at(scope, now, None),
                created_by="system",
            )
            return [_to_payload(row)]

    def extract_from_safety_incident(self, incident_id: int) -> list[MemoryPayload]:
        with session_scope(self.engine) as session:
            incident = SafetyIncidentRepository(session).get(incident_id)
            if incident is None:
                raise LearningMemoryNotFoundError("safety incident not found")

            message = _safe_fragment(incident.message)
            content = (
                f"Safety incident recorded for {incident.category}. "
                f"Severity: {incident.severity}. Status: {incident.status}."
            )
            if message:
                content = f"{content} Lesson: {message}"
            _ensure_safe_memory_text(f"Safety incident: {incident.reason_code}", content)
            row, _ = AgentLearningMemoryRepository(session).get_or_create_active(
                memory_type="safety_incident_lesson",
                scope="global",
                source_type="safety_incident",
                source_id=incident.id,
                reason_code=incident.reason_code,
                title=f"Safety incident: {incident.reason_code}",
                content=content,
                evidence_payload={
                    "safety_incident_id": incident.id,
                    "severity": incident.severity,
                    "category": incident.category,
                    "resource_type": incident.resource_type,
                    "resource_id": incident.resource_id,
                    "status": incident.status,
                },
                confidence=Decimal("1"),
                importance=Decimal("0.9"),
                now=_utcnow(),
                created_by="system",
            )
            return [_to_payload(row)]

    def retrieve(
        self,
        symbol: str | None = None,
        strategy_skill_id: int | None = None,
        memory_types: list[str] | None = None,
        limit: int = 8,
    ) -> list[MemoryPayload]:
        if limit <= 0:
            return []

        with session_scope(self.engine) as session:
            rows = AgentLearningMemoryRepository(session).list_active(
                symbol=symbol,
                strategy_skill_id=strategy_skill_id,
                memory_types=memory_types,
                limit=limit,
                now=_utcnow(),
            )
            return [_to_payload(row) for row in rows]

    def retrieve_for_prompt(
        self,
        symbol: str | None = None,
        strategy_skill_id: int | None = None,
        memory_types: list[str] | None = None,
        limit: int = 8,
        max_chars: int = 3000,
    ) -> list[MemoryPayload]:
        if limit <= 0 or max_chars <= 0:
            return []

        with session_scope(self.engine) as session:
            rows = AgentLearningMemoryRepository(session).list_active(
                symbol=symbol,
                strategy_skill_id=strategy_skill_id,
                memory_types=memory_types,
                limit=max(limit * 10, 50),
                now=_utcnow(),
            )
            results: list[MemoryPayload] = []
            used_chars = 0
            for row in rows:
                if _decimal(row.confidence) < MIN_PROMPT_MEMORY_CONFIDENCE:
                    continue
                if contains_unsafe_agent_text([row.title, row.content]):
                    continue
                row_chars = len(row.title) + len(row.content)
                if used_chars + row_chars > max_chars:
                    continue
                results.append(_to_payload(row))
                used_chars += row_chars
                if len(results) >= limit:
                    break
            return results

    def retire(self, memory_id: int, operator: str, reason: str) -> MemoryPayload:
        with session_scope(self.engine) as session:
            repo = AgentLearningMemoryRepository(session)
            try:
                row = repo.retire(
                    memory_id,
                    retired_by=operator,
                    retired_reason=reason,
                    now=_utcnow(),
                )
            except ValueError as exc:
                raise LearningMemoryNotFoundError(str(exc)) from exc
            return _to_payload(row)

    def _create_memory(
        self,
        *,
        memory_type: str,
        scope: str,
        title: str,
        content: str,
        reason_code: str,
        source_type: str,
        source_id: int,
        evidence_payload: dict[str, Any],
        confidence: Decimal,
        importance: Decimal,
        created_by: str,
        symbol: str | None = None,
        strategy_skill_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryPayload:
        title = title.strip()[:160]
        content = content.strip()[:4000]
        _ensure_safe_memory_text(title, content)
        now = _utcnow()
        resolved_expires_at = _default_expires_at(scope, now, expires_at)

        with session_scope(self.engine) as session:
            row, _ = AgentLearningMemoryRepository(session).get_or_create_active(
                memory_type=memory_type,
                scope=scope,
                source_type=source_type,
                source_id=source_id,
                reason_code=reason_code,
                title=title,
                content=content,
                evidence_payload=evidence_payload,
                confidence=_decimal(confidence),
                importance=_decimal(importance),
                now=now,
                symbol=symbol,
                strategy_skill_id=strategy_skill_id,
                expires_at=resolved_expires_at,
                created_by=created_by,
            )
            return _to_payload(row)


def _to_payload(row: AgentLearningMemoryORM) -> MemoryPayload:
    return MemoryPayload(
        id=row.id,
        memory_type=row.memory_type,
        scope=row.scope,
        symbol=row.symbol,
        strategy_skill_id=row.strategy_skill_id,
        title=row.title,
        content=row.content,
        reason_code=row.reason_code,
        confidence=_decimal(row.confidence),
        importance=_decimal(row.importance),
        source_type=row.source_type,
        source_id=row.source_id,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _default_expires_at(
    scope: str,
    now: datetime,
    expires_at: datetime | None,
) -> datetime | None:
    if expires_at is not None:
        return expires_at
    if scope == "symbol":
        return now + timedelta(days=DEFAULT_SYMBOL_MEMORY_EXPIRY_DAYS)
    return None


def _ensure_safe_memory_text(title: str, content: str) -> None:
    if contains_unsafe_agent_text([title, content]):
        raise LearningMemoryError("unsafe memory content")


def _safe_fragment(value: str | None, limit: int = 500) -> str:
    if not value:
        return ""
    text = sanitize_error_message(value.strip(), max_chars=limit)
    if contains_unsafe_agent_text([text]):
        return ""
    return text


def _json_loads(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _first_summary_reason_code(summary: Any) -> str:
    if isinstance(summary, dict):
        reasons = summary.get("reasons")
        if isinstance(reasons, list):
            for reason in reasons:
                if isinstance(reason, dict) and reason.get("code"):
                    return str(reason["code"])[:128]
                if isinstance(reason, str) and reason:
                    return reason[:128]
    return "research_validation_failed"


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
