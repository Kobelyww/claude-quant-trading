from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from quant_trading.agents.candidate_reviews import (
    CandidateReviewConflictError,
    CandidateReviewNotFoundError,
    CandidateReviewValidationError,
    approve_strategy_candidate,
    candidate_review_payload,
    refresh_candidate_backtest_status,
    reject_strategy_candidate,
)
from quant_trading.storage.db import session_scope
from quant_trading.storage.repositories import AgentCandidateReviewRepository

router = APIRouter(prefix="/agent-candidates", tags=["agent-candidates"])


class CandidateDecisionRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1, max_length=1000)

    @field_validator("operator", "note")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


@router.get("")
def list_agent_candidates(
    request: Request,
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = AgentCandidateReviewRepository(session).list_recent(
            status=status,
            symbol=symbol,
            limit=limit,
        )
        return [candidate_review_payload(row) for row in rows]


@router.get("/{candidate_review_id}")
def get_agent_candidate(
    candidate_review_id: int,
    request: Request,
) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = AgentCandidateReviewRepository(session).get(candidate_review_id)
        if row is None:
            raise HTTPException(status_code=404, detail="candidate review not found")
        return candidate_review_payload(row)


@router.post("/{agent_run_id}/approve")
def approve_agent_candidate(
    agent_run_id: int,
    payload: CandidateDecisionRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        row = approve_strategy_candidate(
            request.app.state.engine,
            agent_run_id,
            operator=payload.operator,
            note=payload.note,
            settings=request.app.state.settings,
        )
    except (
        CandidateReviewNotFoundError,
        CandidateReviewConflictError,
        CandidateReviewValidationError,
    ) as exc:
        _raise_candidate_review_http_error(exc)
    return candidate_review_payload(row)


@router.post("/{agent_run_id}/reject")
def reject_agent_candidate(
    agent_run_id: int,
    payload: CandidateDecisionRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        row = reject_strategy_candidate(
            request.app.state.engine,
            agent_run_id,
            operator=payload.operator,
            note=payload.note,
        )
    except (
        CandidateReviewNotFoundError,
        CandidateReviewConflictError,
        CandidateReviewValidationError,
    ) as exc:
        _raise_candidate_review_http_error(exc)
    return candidate_review_payload(row)


@router.post("/{candidate_review_id}/refresh-backtest")
def refresh_agent_candidate_backtest(
    candidate_review_id: int,
    request: Request,
) -> dict[str, Any]:
    try:
        row = refresh_candidate_backtest_status(
            request.app.state.engine,
            candidate_review_id,
        )
    except (CandidateReviewNotFoundError, CandidateReviewConflictError) as exc:
        _raise_candidate_review_http_error(exc)
    return candidate_review_payload(row)


def _raise_candidate_review_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, CandidateReviewNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, CandidateReviewConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, CandidateReviewValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc
