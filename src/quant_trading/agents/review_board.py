from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import Engine, select

from quant_trading.agents.memory import LearningMemoryService
from quant_trading.agents.output_safety import contains_unsafe_agent_text
from quant_trading.security import sanitize_error_message
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    DataQualityReportORM,
    ResearchValidationReportORM,
    SafetyIncidentORM,
)
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentReviewBoardRunRepository,
    AgentReviewBoardVoteRepository,
    DataQualityReportRepository,
    ResearchValidationReportRepository,
    StrategySkillRepository,
)


SUPPORTED_REVIEWER_VOTES = {"block", "needs_review", "pass"}
READY_FOR_PAPER_RESEARCH = "ready_for_paper_research"
READINESS_NEEDS_REVIEW = "needs_review"
READINESS_NOT_READY = "not_ready"
VALIDATION_STATUS_FAILED = "failed"
VALIDATION_STATUS_NEEDS_REVIEW = "needs_review"
VALIDATION_STATUS_PASSED = "passed"


@dataclass(frozen=True)
class ReviewBoardVote:
    reviewer_role: str
    vote: str
    reason_code: str
    rationale: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class CoordinatorRecommendation:
    final_recommendation: str
    blocking_reason_codes: list[str]
    summary: dict[str, Any]
    board_run_id: int = 0


class ReviewBoardService:
    def __init__(self, engine: Engine, settings: Any | None = None):
        self.engine = engine
        self.settings = settings

    def run_for_candidate_review(
        self,
        candidate_review_id: int,
    ) -> CoordinatorRecommendation:
        started_at = _utcnow()
        board_run_id: int | None = None
        try:
            with session_scope(self.engine) as session:
                candidate = AgentCandidateReviewRepository(session).get(
                    candidate_review_id
                )
                if candidate is None:
                    raise ValueError("candidate review not found")
                strategy_skill_id = _strategy_skill_id(session, candidate)
                symbol = candidate.symbol

            memories = LearningMemoryService(self.engine).retrieve(
                symbol=symbol,
                strategy_skill_id=strategy_skill_id,
                limit=8,
            )
            memory_ids = [memory.id for memory in memories]
            with session_scope(self.engine) as session:
                board_run = AgentReviewBoardRunRepository(session).create_running(
                    subject_type="strategy_candidate",
                    subject_id=candidate_review_id,
                    memory_ids=memory_ids,
                    now=_utcnow(),
                )
                board_run_id = board_run.id

            with session_scope(self.engine) as session:
                candidate = AgentCandidateReviewRepository(session).get(
                    candidate_review_id
                )
                if candidate is None:
                    raise ValueError("candidate review not found")
                validation = _load_validation_report(session, candidate)
                data_quality = _load_data_quality_report(
                    session,
                    candidate,
                    validation,
                )
                votes = _deterministic_votes(
                    session=session,
                    candidate=candidate,
                    validation=validation,
                    data_quality=data_quality,
                    memories_count=len(memories),
                )
                vote_repo = AgentReviewBoardVoteRepository(session)
                for vote in votes:
                    vote_repo.record(
                        board_run_id=board_run_id,
                        reviewer_role=vote.reviewer_role,
                        vote=vote.vote,
                        reason_code=vote.reason_code,
                        rationale=vote.rationale,
                        evidence_payload=vote.evidence,
                        now=_utcnow(),
                    )

                recommendation = coordinator_recommendation(
                    votes,
                    readiness_floor=validation.readiness_floor if validation else "",
                    data_quality_status=data_quality.status if data_quality else "",
                )
                AgentReviewBoardRunRepository(session).mark_completed(
                    board_run_id,
                    final_recommendation=recommendation.final_recommendation,
                    blocking_reason_codes=recommendation.blocking_reason_codes,
                    summary_payload=recommendation.summary,
                    finished_at=_utcnow(),
                    duration_ms=_duration_ms(started_at, _utcnow()),
                )
                return CoordinatorRecommendation(
                    final_recommendation=recommendation.final_recommendation,
                    blocking_reason_codes=recommendation.blocking_reason_codes,
                    summary=recommendation.summary,
                    board_run_id=board_run_id,
                )
        except Exception as exc:
            message = sanitize_error_message(
                exc,
                settings=self.settings,
                max_chars=1000,
            )
            if board_run_id is not None:
                try:
                    with session_scope(self.engine) as session:
                        AgentReviewBoardRunRepository(session).mark_failed(
                            board_run_id,
                            error_message=message,
                            finished_at=_utcnow(),
                            duration_ms=_duration_ms(started_at, _utcnow()),
                        )
                except Exception:
                    pass
            raise


def parse_reviewer_vote(content: str, reviewer_role: str) -> ReviewBoardVote:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return _invalid_vote(reviewer_role)

    if not isinstance(payload, dict):
        return _invalid_vote(reviewer_role)

    vote = str(payload.get("vote", "")).strip()
    reason_code = str(payload.get("reason_code", "")).strip() or "reviewer_vote"
    rationale = str(payload.get("rationale", "")).strip()
    evidence = payload.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}

    if vote not in SUPPORTED_REVIEWER_VOTES:
        return _invalid_vote(reviewer_role)
    if contains_unsafe_agent_text(_reviewer_vote_safety_text(rationale, evidence)):
        return ReviewBoardVote(
            reviewer_role,
            "needs_review",
            "unsafe_reviewer_output",
            "Reviewer output contained unsafe text and requires human review.",
            {},
        )

    return ReviewBoardVote(reviewer_role, vote, reason_code, rationale, evidence)


def coordinator_recommendation(
    votes: list[ReviewBoardVote],
    readiness_floor: str,
    data_quality_status: str,
) -> CoordinatorRecommendation:
    normalized_floor = (readiness_floor or "").strip().lower()
    normalized_data_quality = (data_quality_status or "").strip().lower()
    blocking_reason_codes: list[str] = []
    final_recommendation = "needs_more_research"

    if normalized_data_quality == "failed":
        blocking_reason_codes.append("data_quality_failed")
        final_recommendation = "reject"
    else:
        block_reason_codes = [
            vote.reason_code for vote in votes if vote.vote == "block" and vote.reason_code
        ]
        needs_review_reason_codes = [
            vote.reason_code
            for vote in votes
            if vote.vote == "needs_review" and vote.reason_code
        ]
        blocking_reason_codes.extend(block_reason_codes)
        blocking_reason_codes.extend(needs_review_reason_codes)
        if normalized_data_quality != "passed":
            blocking_reason_codes.append("data_quality_not_passed")
        readiness_floor_reason = _readiness_floor_block_reason(normalized_floor)
        if readiness_floor_reason:
            blocking_reason_codes.append(readiness_floor_reason)
        if (
            not block_reason_codes
            and not needs_review_reason_codes
            and normalized_data_quality == "passed"
            and readiness_floor_reason is None
        ):
            final_recommendation = "ready_for_paper_research_consideration"

    blocking_reason_codes = _deduplicate(blocking_reason_codes)
    summary = {
        "readiness_floor": normalized_floor or "unknown",
        "data_quality_status": normalized_data_quality or "unknown",
        "vote_counts": {
            "block": sum(1 for vote in votes if vote.vote == "block"),
            "needs_review": sum(1 for vote in votes if vote.vote == "needs_review"),
            "pass": sum(1 for vote in votes if vote.vote == "pass"),
        },
        "reviewer_votes": [
            {
                "reviewer_role": vote.reviewer_role,
                "vote": vote.vote,
                "reason_code": vote.reason_code,
            }
            for vote in votes
        ],
        "coordinator_rationale": _coordinator_rationale(
            final_recommendation,
            blocking_reason_codes,
        ),
    }
    return CoordinatorRecommendation(
        final_recommendation,
        blocking_reason_codes,
        summary,
    )


def _invalid_vote(reviewer_role: str) -> ReviewBoardVote:
    return ReviewBoardVote(
        reviewer_role,
        "needs_review",
        "invalid_reviewer_output",
        "Reviewer output was not valid review-board JSON.",
        {},
    )


def _reviewer_vote_safety_text(
    rationale: str,
    evidence: dict[str, Any],
) -> Iterator[str]:
    yield rationale
    yield from _evidence_text_values(evidence)


def _evidence_text_values(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _evidence_text_values(key)
            yield from _evidence_text_values(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _evidence_text_values(item)
        return
    if isinstance(value, (int, float, bool)):
        yield str(value)


def _readiness_floor_block_reason(normalized_floor: str) -> str | None:
    if normalized_floor == READY_FOR_PAPER_RESEARCH:
        return None
    if normalized_floor == READINESS_NOT_READY:
        return "readiness_floor_not_ready"
    if normalized_floor == READINESS_NEEDS_REVIEW:
        return "readiness_floor_needs_review"
    return "readiness_floor_unknown_or_in_progress"


def _deduplicate(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _coordinator_rationale(
    final_recommendation: str,
    blocking_reason_codes: list[str],
) -> str:
    if final_recommendation == "reject":
        return "Reject this research candidate until failed data quality is resolved."
    if final_recommendation == "ready_for_paper_research_consideration":
        return (
            "All deterministic reviewers passed; candidate may be considered for "
            "human-reviewed paper research."
        )
    if blocking_reason_codes:
        return (
            "Additional research review is required before this candidate can advance."
        )
    return "Additional research review is required before this candidate can advance."


def _deterministic_votes(
    *,
    session,
    candidate: AgentCandidateReviewORM,
    validation: ResearchValidationReportORM | None,
    data_quality: DataQualityReportORM | None,
    memories_count: int,
) -> list[ReviewBoardVote]:
    return [
        _data_steward_vote(data_quality),
        _strategy_researcher_vote(session, candidate),
        _risk_officer_vote(validation),
        _validation_reviewer_vote(validation),
        _operations_reviewer_vote(session, candidate, memories_count),
    ]


def _data_steward_vote(data_quality: DataQualityReportORM | None) -> ReviewBoardVote:
    if data_quality is None:
        return ReviewBoardVote(
            "data_steward",
            "needs_review",
            "data_quality_report_missing",
            "Data quality report is missing for this research candidate.",
            {},
        )
    evidence = {
        "data_quality_report_id": data_quality.id,
        "status": data_quality.status,
        "severity": data_quality.severity,
        "missing_bar_count": data_quality.missing_bar_count,
        "invalid_ohlc_count": data_quality.invalid_ohlc_count,
        "stale_data": data_quality.stale_data,
    }
    if data_quality.status == "failed":
        return ReviewBoardVote(
            "data_steward",
            "block",
            "data_quality_failed",
            "Data quality failed and must be resolved before further research review.",
            evidence,
        )
    if data_quality.status != "passed":
        return ReviewBoardVote(
            "data_steward",
            "needs_review",
            "data_quality_not_passed",
            "Data quality has not passed and requires review before advancing.",
            evidence,
        )
    return ReviewBoardVote(
        "data_steward",
        "pass",
        "data_quality_passed",
        "Data quality passed deterministic checks.",
        evidence,
    )


def _strategy_researcher_vote(session, candidate: AgentCandidateReviewORM) -> ReviewBoardVote:
    payload = _json_object_loads(candidate.candidate_payload)
    if payload is None:
        return ReviewBoardVote(
            "strategy_researcher",
            "needs_review",
            "strategy_payload_invalid",
            "Strategy candidate payload is not a JSON object.",
            {
                "strategy_name": candidate.strategy_name,
                "candidate_review_id": candidate.id,
            },
        )
    strategy_skill_key = str(
        payload.get("strategy_skill_key")
        or payload.get("strategy_name")
        or candidate.strategy_name
        or "ma_cross"
    ).strip()
    if not strategy_skill_key:
        strategy_skill_key = "ma_cross"

    skill = StrategySkillRepository(session).get_active(strategy_skill_key)
    evidence = {
        "strategy_skill_key": strategy_skill_key,
        "strategy_name": candidate.strategy_name,
        "candidate_review_id": candidate.id,
        "skill_found": skill is not None,
    }
    if skill is None or strategy_skill_key != "ma_cross":
        return ReviewBoardVote(
            "strategy_researcher",
            "needs_review",
            "strategy_skill_missing_or_unsupported",
            "Strategy skill is missing or unsupported for deterministic review.",
            evidence,
        )
    return ReviewBoardVote(
        "strategy_researcher",
        "pass",
        "strategy_skill_supported",
        "Strategy skill is supported by the deterministic registry.",
        evidence | {"strategy_skill_id": skill.id, "skill_version": skill.version},
    )


def _risk_officer_vote(
    validation: ResearchValidationReportORM | None,
) -> ReviewBoardVote:
    if validation is None:
        return ReviewBoardVote(
            "risk_officer",
            "needs_review",
            "validation_report_missing",
            "Risk review needs a research validation report.",
            {},
        )
    summary = _json_loads(validation.summary_payload)
    reason_text = _validation_reason_text(summary)
    evidence = {
        "research_validation_report_id": validation.id,
        "validation_status": validation.validation_status,
        "readiness_floor": validation.readiness_floor,
        "reason_text": reason_text[:500],
    }
    lowered = reason_text.lower()
    if "drawdown" in lowered or "overfit" in lowered:
        return ReviewBoardVote(
            "risk_officer",
            "needs_review",
            "risk_drawdown_or_overfit_review",
            "Validation reasons include drawdown or overfit concerns for review.",
            evidence,
        )
    return ReviewBoardVote(
        "risk_officer",
        "pass",
        "risk_review_clear",
        "No drawdown or overfit reason was detected in validation reasons.",
        evidence,
    )


def _validation_reviewer_vote(
    validation: ResearchValidationReportORM | None,
) -> ReviewBoardVote:
    if validation is None:
        return ReviewBoardVote(
            "validation_reviewer",
            "needs_review",
            "validation_report_missing",
            "Research validation report is missing.",
            {},
        )
    validation_status = str(validation.validation_status or "").strip().lower()
    readiness_floor = str(validation.readiness_floor or "").strip().lower()
    evidence = {
        "research_validation_report_id": validation.id,
        "validation_status": validation.validation_status,
        "readiness_floor": validation.readiness_floor,
    }
    if validation_status == VALIDATION_STATUS_FAILED:
        return ReviewBoardVote(
            "validation_reviewer",
            "block",
            "validation_failed",
            "Validation failed deterministic research checks.",
            evidence,
        )
    if readiness_floor == READINESS_NOT_READY:
        return ReviewBoardVote(
            "validation_reviewer",
            "block",
            "readiness_floor_not_ready",
            "Deterministic validation floor is not ready.",
            evidence,
        )
    if (
        validation_status == VALIDATION_STATUS_NEEDS_REVIEW
        or readiness_floor == READINESS_NEEDS_REVIEW
    ):
        return ReviewBoardVote(
            "validation_reviewer",
            "needs_review",
            "validation_needs_review",
            "Validation requires additional research review.",
            evidence,
        )
    if (
        validation_status != VALIDATION_STATUS_PASSED
        or readiness_floor != READY_FOR_PAPER_RESEARCH
    ):
        return ReviewBoardVote(
            "validation_reviewer",
            "needs_review",
            "validation_unknown_or_in_progress",
            "Validation status or readiness floor is unknown or still in progress.",
            evidence,
        )
    return ReviewBoardVote(
        "validation_reviewer",
        "pass",
        "validation_passed",
        "Validation passed deterministic research checks.",
        evidence,
    )


def _operations_reviewer_vote(
    session,
    candidate: AgentCandidateReviewORM,
    memories_count: int,
) -> ReviewBoardVote:
    unresolved_incidents = _linked_unresolved_safety_incidents(session, candidate)
    if unresolved_incidents:
        return ReviewBoardVote(
            "operations_reviewer",
            "needs_review",
            "unresolved_linked_safety_incident",
            "Unresolved pre-live safety incident is linked to this candidate.",
            {
                "candidate_review_id": candidate.id,
                "linked_incident_ids": [incident.id for incident in unresolved_incidents],
                "linked_incident_reason_codes": [
                    incident.reason_code for incident in unresolved_incidents
                ],
                "retrieved_memory_count": memories_count,
            },
        )
    return ReviewBoardVote(
        "operations_reviewer",
        "pass",
        "no_unresolved_linked_safety_incident",
        "V1 found no unresolved linked pre-live safety incident for this candidate.",
        {
            "candidate_review_id": candidate.id,
            "linked_incident_check": "not_linked_in_v1",
            "retrieved_memory_count": memories_count,
        },
    )


def _linked_unresolved_safety_incidents(
    session,
    candidate: AgentCandidateReviewORM,
) -> list[SafetyIncidentORM]:
    return list(
        session.scalars(
            select(SafetyIncidentORM)
            .where(
                SafetyIncidentORM.resource_type == "agent_candidate_review",
                SafetyIncidentORM.resource_id == candidate.id,
                SafetyIncidentORM.status.in_(("open", "acknowledged")),
            )
            .order_by(SafetyIncidentORM.id.asc())
            .limit(10)
        ).all()
    )


def _load_validation_report(
    session,
    candidate: AgentCandidateReviewORM,
) -> ResearchValidationReportORM | None:
    if candidate.research_validation_report_id is not None:
        return ResearchValidationReportRepository(session).get(
            candidate.research_validation_report_id
        )
    return ResearchValidationReportRepository(session).get_by_candidate_review_id(
        candidate.id
    )


def _load_data_quality_report(
    session,
    candidate: AgentCandidateReviewORM,
    validation: ResearchValidationReportORM | None,
) -> DataQualityReportORM | None:
    report_id = candidate.data_quality_report_id
    if report_id is None and validation is not None:
        report_id = validation.data_quality_report_id
    if report_id is not None:
        return DataQualityReportRepository(session).get(report_id)
    reports = DataQualityReportRepository(session).list_recent(
        candidate_review_id=candidate.id,
        limit=1,
    )
    return reports[0] if reports else None


def _strategy_skill_id(session, candidate: AgentCandidateReviewORM) -> int | None:
    payload = _json_object_loads(candidate.candidate_payload)
    if payload is None:
        return None
    skill_key = str(
        payload.get("strategy_skill_key")
        or payload.get("strategy_name")
        or candidate.strategy_name
        or "ma_cross"
    ).strip()
    if not skill_key:
        skill_key = "ma_cross"
    skill = StrategySkillRepository(session).get_active(skill_key)
    return skill.id if skill is not None else None


def _validation_reason_text(summary: Any) -> str:
    if isinstance(summary, dict):
        reasons = summary.get("reasons")
        if isinstance(reasons, list):
            return " ".join(_reason_fragment(reason) for reason in reasons)
    return ""


def _reason_fragment(reason: Any) -> str:
    if isinstance(reason, dict):
        return " ".join(
            str(reason.get(key, ""))
            for key in ("code", "reason_code", "message", "detail")
            if reason.get(key)
        )
    return str(reason)


def _json_loads(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _json_object_loads(value: str | None) -> dict[str, Any] | None:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(0, int((finished_at - started_at).total_seconds() * 1000))
