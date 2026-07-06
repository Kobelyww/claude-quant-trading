from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from quant_trading.agents.memory import (
    LearningMemoryError,
    LearningMemoryNotFoundError,
    LearningMemoryService,
    MemoryPayload,
)
from quant_trading.agents.review_board import ReviewBoardService
from quant_trading.security import sanitize_error_message
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import (
    AgentLearningMemoryORM,
    AgentReviewBoardRunORM,
    AgentReviewBoardVoteORM,
    StrategySkillORM,
)
from quant_trading.storage.repositories import (
    AgentLearningMemoryRepository,
    AgentReviewBoardRunRepository,
    AgentReviewBoardVoteRepository,
    StrategySkillRepository,
)

router = APIRouter(prefix="/agents", tags=["agent-intelligence"])


class RetireMemoryRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("operator", "reason")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


@router.get("/skills")
def list_strategy_skills(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    limit = _bounded_limit(limit)
    with session_scope(request.app.state.engine) as session:
        repo = StrategySkillRepository(session)
        repo.ensure_seeded(_utcnow())
        return [_strategy_skill_payload(row) for row in repo.list_active(limit=limit)]


@router.get("/skills/{skill_key}")
def get_strategy_skill(skill_key: str, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        repo = StrategySkillRepository(session)
        repo.ensure_seeded(_utcnow())
        row = repo.get_active(skill_key)
        if row is None:
            raise HTTPException(status_code=404, detail="strategy skill not found")
        return _strategy_skill_payload(row)


@router.get("/memories")
def list_learning_memories(
    request: Request,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with session_scope(request.app.state.engine) as session:
        rows = AgentLearningMemoryRepository(session).list_active(
            symbol=symbol,
            limit=_bounded_limit(limit),
            now=_utcnow(),
        )
        return [_memory_row_payload(row) for row in rows]


@router.post("/memories/{memory_id}/retire")
def retire_learning_memory(
    memory_id: int,
    payload: RetireMemoryRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        LearningMemoryService(request.app.state.engine).retire(
            memory_id,
            operator=payload.operator,
            reason=payload.reason,
        )
    except LearningMemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LearningMemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with session_scope(request.app.state.engine) as session:
        row = AgentLearningMemoryRepository(session).get(memory_id)
        if row is None:
            raise HTTPException(status_code=404, detail="agent learning memory not found")
        return _memory_row_payload(row)


@router.get("/review-board-runs")
def list_review_board_runs(
    request: Request,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with session_scope(request.app.state.engine) as session:
        rows = AgentReviewBoardRunRepository(session).list_recent(
            limit=_bounded_limit(limit)
        )
        return [_review_board_run_payload(row) for row in rows]


@router.get("/review-board-runs/{run_id}")
def get_review_board_run(run_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        run = AgentReviewBoardRunRepository(session).get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="review board run not found")
        votes = AgentReviewBoardVoteRepository(session).list_for_board(run.id)
        payload = _review_board_run_payload(run)
        payload["votes"] = [_review_board_vote_payload(vote) for vote in votes]
        return payload


@router.post("/candidate-reviews/{candidate_review_id}/extract-memories")
def extract_candidate_review_memories(
    candidate_review_id: int,
    request: Request,
) -> list[dict[str, Any]]:
    try:
        memories = LearningMemoryService(
            request.app.state.engine
        ).extract_from_candidate_review(candidate_review_id)
    except LearningMemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LearningMemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_memory_service_payload(memory) for memory in memories]


@router.post("/research-validation-reports/{report_id}/extract-memories")
def extract_research_validation_memories(
    report_id: int,
    request: Request,
) -> list[dict[str, Any]]:
    try:
        memories = LearningMemoryService(
            request.app.state.engine
        ).extract_from_validation_report(report_id)
    except LearningMemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LearningMemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_memory_service_payload(memory) for memory in memories]


@router.post("/candidate-reviews/{candidate_review_id}/review-board")
def run_candidate_review_board(
    candidate_review_id: int,
    request: Request,
) -> dict[str, Any]:
    try:
        ReviewBoardService(request.app.state.engine).run_for_candidate_review(
            candidate_review_id
        )
    except ValueError as exc:
        _raise_review_board_http_error(exc)
    except Exception as exc:
        message = sanitize_error_message(exc, max_chars=1000)
        raise HTTPException(status_code=400, detail=message) from exc

    with session_scope(request.app.state.engine) as session:
        run = session.scalar(
            select(AgentReviewBoardRunORM)
            .where(
                AgentReviewBoardRunORM.subject_type == "strategy_candidate",
                AgentReviewBoardRunORM.subject_id == candidate_review_id,
            )
            .order_by(AgentReviewBoardRunORM.id.desc())
            .limit(1)
        )
        if run is None:
            raise HTTPException(status_code=404, detail="review board run not found")
        payload = _review_board_run_payload(run)
        votes = AgentReviewBoardVoteRepository(session).list_for_board(run.id)
        payload["votes"] = [_review_board_vote_payload(vote) for vote in votes]
        return payload


def _strategy_skill_payload(row: StrategySkillORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "skill_key": row.skill_key,
        "version": row.version,
        "display_name": row.display_name,
        "description": row.description,
        "status": row.status,
        "template_type": row.template_type,
        "supported_markets": _json_loads(row.supported_markets_payload, []),
        "required_data_fields": _json_loads(row.required_data_fields_payload, []),
        "parameter_schema": _json_loads(row.parameter_schema_payload, {}),
        "validation_rules": _json_loads(row.validation_rules_payload, {}),
        "risk_notes": _json_loads(row.risk_notes_payload, {}),
        "prompt_guidance": row.prompt_guidance,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _memory_row_payload(row: AgentLearningMemoryORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "memory_type": row.memory_type,
        "scope": row.scope,
        "symbol": row.symbol,
        "strategy_skill_id": row.strategy_skill_id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "title": row.title,
        "content": row.content,
        "reason_code": row.reason_code,
        "evidence": _json_loads(row.evidence_payload, {}),
        "confidence": str(row.confidence),
        "importance": str(row.importance),
        "status": row.status,
        "expires_at": _iso(row.expires_at),
        "created_at": _iso(row.created_at),
        "created_by": row.created_by,
        "retired_at": _iso(row.retired_at),
        "retired_by": row.retired_by,
        "retired_reason": row.retired_reason,
    }


def _memory_service_payload(memory: MemoryPayload) -> dict[str, Any]:
    return {
        "id": memory.id,
        "memory_type": memory.memory_type,
        "scope": memory.scope,
        "symbol": memory.symbol,
        "strategy_skill_id": memory.strategy_skill_id,
        "source_type": memory.source_type,
        "source_id": memory.source_id,
        "title": memory.title,
        "content": memory.content,
        "reason_code": memory.reason_code,
        "confidence": str(memory.confidence),
        "importance": str(memory.importance),
    }


def _review_board_run_payload(row: AgentReviewBoardRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "status": row.status,
        "coordinator_agent_run_id": row.coordinator_agent_run_id,
        "final_recommendation": row.final_recommendation,
        "blocking_reason_codes": _json_loads(
            row.blocking_reason_codes_payload,
            [],
        ),
        "memory_ids": _json_loads(row.memory_ids_payload, []),
        "summary": _json_loads(row.summary_payload, {}),
        "created_at": _iso(row.created_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
    }


def _review_board_vote_payload(row: AgentReviewBoardVoteORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "board_run_id": row.board_run_id,
        "reviewer_role": row.reviewer_role,
        "agent_run_id": row.agent_run_id,
        "vote": row.vote,
        "reason_code": row.reason_code,
        "rationale": row.rationale,
        "evidence": _json_loads(row.evidence_payload, {}),
        "created_at": _iso(row.created_at),
    }


def _bounded_limit(value: int) -> int:
    return max(1, min(value, 100))


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
    return loaded


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _raise_review_board_http_error(exc: ValueError) -> NoReturn:
    message = sanitize_error_message(exc, max_chars=1000)
    status_code = 404 if "not found" in message.lower() else 400
    raise HTTPException(status_code=status_code, detail=message) from exc
