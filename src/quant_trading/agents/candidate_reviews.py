from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any, Callable

from sqlalchemy import Engine

from quant_trading.agents.candidates import BACKTEST_MA_CROSS, STATUS_PASSED
from quant_trading.agents.models import AGENT_STRATEGY_IDEA
from quant_trading.config import AppSettings
from quant_trading.jobs.queue import make_queue
from quant_trading.jobs.runtime import utcnow
from quant_trading.jobs.service import QueueLike, submit_job_run
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import AgentCandidateReviewORM
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentRunRepository,
    JobRunRepository,
)


STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_BACKTEST_SUBMITTED = "backtest_submitted"
STATUS_BACKTEST_SUCCEEDED = "backtest_succeeded"
STATUS_BACKTEST_FAILED = "backtest_failed"
STATUS_REVIEW_REQUESTED = "review_requested"
STATUS_REVIEW_SUCCEEDED = "review_succeeded"
STATUS_REVIEW_FAILED = "review_failed"

_SUBMITTED_STATUSES = {
    STATUS_APPROVED,
    STATUS_BACKTEST_SUBMITTED,
    STATUS_BACKTEST_SUCCEEDED,
    STATUS_BACKTEST_FAILED,
    STATUS_REVIEW_REQUESTED,
    STATUS_REVIEW_SUCCEEDED,
    STATUS_REVIEW_FAILED,
}
_MAX_OPERATOR_LENGTH = 128
_MAX_NOTE_LENGTH = 1000
_MAX_ERROR_LENGTH = 1000


class _JobRunIdCaptureQueue:
    def __init__(self, queue: QueueLike):
        self.queue = queue
        self.job_run_id: int | None = None

    def enqueue(self, func, *args):
        if len(args) >= 2:
            try:
                self.job_run_id = int(args[1])
            except (TypeError, ValueError):
                self.job_run_id = None
        return self.queue.enqueue(func, *args)


class _JobRunIdCaptureQueueFactory:
    def __init__(self, queue_factory: Callable[[str], QueueLike]):
        self.queue_factory = queue_factory
        self.queue: _JobRunIdCaptureQueue | None = None

    def __call__(self, redis_url: str) -> _JobRunIdCaptureQueue:
        self.queue = _JobRunIdCaptureQueue(self.queue_factory(redis_url))
        return self.queue

    @property
    def job_run_id(self) -> int | None:
        return self.queue.job_run_id if self.queue is not None else None


class CandidateReviewError(ValueError):
    pass


class CandidateReviewNotFoundError(CandidateReviewError):
    pass


class CandidateReviewConflictError(CandidateReviewError):
    pass


class CandidateReviewValidationError(CandidateReviewError):
    pass


def candidate_review_payload(row: AgentCandidateReviewORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_agent_run_id": row.source_agent_run_id,
        "status": row.status,
        "symbol": row.symbol,
        "strategy_name": row.strategy_name,
        "candidate_payload": _json_loads(row.candidate_payload),
        "backtest_request_payload": _json_loads(row.backtest_request_payload),
        "operator": row.operator,
        "operator_note": row.operator_note,
        "backtest_job_run_id": row.backtest_job_run_id,
        "backtest_run_id": row.backtest_run_id,
        "review_agent_run_id": row.review_agent_run_id,
        "error_message": row.error_message,
        "decided_at": _isoformat(row.decided_at),
        "created_at": _isoformat(row.created_at),
        "updated_at": _isoformat(row.updated_at),
    }


def approve_strategy_candidate(
    engine: Engine,
    source_agent_run_id: int,
    operator: str,
    note: str,
    settings: AppSettings,
    queue_factory=make_queue,
) -> AgentCandidateReviewORM:
    with session_scope(engine) as session:
        review_repo = AgentCandidateReviewRepository(session)
        existing = review_repo.get_by_source_agent_run_id(source_agent_run_id)
        if existing is not None:
            _raise_approval_conflict(existing.status)

        source = AgentRunRepository(session).get(source_agent_run_id)
        candidate, backtest_request = _validate_source_agent_run(source)
        now = _now()
        review = review_repo.create_decision(
            source_agent_run_id=source_agent_run_id,
            status=STATUS_APPROVED,
            symbol=_required_text(candidate.get("symbol"), "missing candidate symbol"),
            strategy_name=_required_text(
                candidate.get("strategy_name"),
                "missing candidate strategy name",
            ),
            candidate_payload=_json_dumps(candidate),
            backtest_request_payload=_json_dumps(backtest_request),
            operator=_clean_operator(operator),
            operator_note=_clean_note(note),
            decided_at=now,
            created_at=now,
        )
        review_id = review.id

    captured_queue_factory = _JobRunIdCaptureQueueFactory(queue_factory)
    try:
        job = submit_job_run(
            engine,
            settings,
            BACKTEST_MA_CROSS,
            backtest_request["payload"],
            captured_queue_factory,
        )
    except Exception as exc:
        return _mark_submit_failed(
            engine,
            review_id,
            str(exc),
            backtest_job_run_id=captured_queue_factory.job_run_id,
        )

    with session_scope(engine) as session:
        review_repo = AgentCandidateReviewRepository(session)
        job_repo = JobRunRepository(session)
        review = review_repo.get(review_id)
        if review is None:
            raise CandidateReviewNotFoundError("candidate review not found")
        review_repo.mark_backtest_submitted(
            review,
            backtest_job_run_id=job.id,
            updated_at=_now(),
        )
        job_row = job_repo.get(job.id)
        if job_row is not None and job_row.status == "succeeded":
            result_payload = _json_loads(job_row.result_payload)
            run_id = result_payload.get("run_id")
            if isinstance(run_id, int):
                review_repo.mark_backtest_succeeded(
                    review,
                    backtest_run_id=run_id,
                    updated_at=_now(),
                )
            else:
                review_repo.mark_backtest_failed(
                    review,
                    error_message="backtest job did not return run_id",
                    updated_at=_now(),
                )
        elif job_row is not None and job_row.status == "failed":
            review_repo.mark_backtest_failed(
                review,
                error_message=(job_row.error_message or "backtest job failed")[
                    :_MAX_ERROR_LENGTH
                ],
                updated_at=_now(),
            )
        session.expunge(review)
        return review


def reject_strategy_candidate(
    engine: Engine,
    source_agent_run_id: int,
    operator: str,
    note: str,
) -> AgentCandidateReviewORM:
    with session_scope(engine) as session:
        review_repo = AgentCandidateReviewRepository(session)
        existing = review_repo.get_by_source_agent_run_id(source_agent_run_id)
        source = AgentRunRepository(session).get(source_agent_run_id)
        candidate, backtest_request = _validate_source_agent_run(source)
        now = _now()
        if existing is not None:
            if existing.status != STATUS_REJECTED:
                raise CandidateReviewConflictError("cannot reject candidate after approval")
            review = review_repo.update_rejection(
                existing,
                candidate_payload=_json_dumps(candidate),
                backtest_request_payload=_json_dumps(backtest_request),
                operator=_clean_operator(operator),
                operator_note=_clean_note(note),
                decided_at=now,
                updated_at=now,
            )
        else:
            review = review_repo.create_decision(
                source_agent_run_id=source_agent_run_id,
                status=STATUS_REJECTED,
                symbol=_required_text(candidate.get("symbol"), "missing candidate symbol"),
                strategy_name=_required_text(
                    candidate.get("strategy_name"),
                    "missing candidate strategy name",
                ),
                candidate_payload=_json_dumps(candidate),
                backtest_request_payload=_json_dumps(backtest_request),
                operator=_clean_operator(operator),
                operator_note=_clean_note(note),
                decided_at=now,
                created_at=now,
            )
        session.expunge(review)
        return review


def _validate_source_agent_run(source) -> tuple[dict[str, Any], dict[str, Any]]:
    if source is None:
        raise CandidateReviewNotFoundError("source agent run not found")
    if source.agent_type != AGENT_STRATEGY_IDEA:
        raise CandidateReviewValidationError("source agent run is not a strategy idea")
    if source.status != "succeeded":
        raise CandidateReviewValidationError("source agent run has not succeeded")

    result_payload = _strict_json_loads(source.result_payload)
    if result_payload.get("parsed") is not True:
        raise CandidateReviewValidationError("strategy candidate was not parsed")
    if result_payload.get("validation_status") != STATUS_PASSED:
        raise CandidateReviewValidationError("candidate validation did not pass")

    candidate_payload = result_payload.get("candidate_payload")
    if not isinstance(candidate_payload, dict):
        raise CandidateReviewValidationError("missing candidate payload")
    backtest_request_payload = result_payload.get("backtest_request_payload")
    if not isinstance(backtest_request_payload, dict):
        raise CandidateReviewValidationError("missing backtest request payload")
    if backtest_request_payload.get("job_type") != BACKTEST_MA_CROSS:
        raise CandidateReviewValidationError("unsupported backtest job type")
    if not isinstance(backtest_request_payload.get("payload"), dict):
        raise CandidateReviewValidationError("missing backtest request payload")
    if result_payload.get("requires_human_approval") is not True:
        raise CandidateReviewValidationError("candidate does not require human approval")
    _required_text(candidate_payload.get("symbol"), "missing candidate symbol")
    _required_text(candidate_payload.get("strategy_name"), "missing candidate strategy name")
    return candidate_payload, backtest_request_payload


def _mark_submit_failed(
    engine: Engine,
    review_id: int,
    error_message: str,
    *,
    backtest_job_run_id: int | None = None,
) -> AgentCandidateReviewORM:
    with session_scope(engine) as session:
        review_repo = AgentCandidateReviewRepository(session)
        job_repo = JobRunRepository(session)
        review = review_repo.get(review_id)
        if review is None:
            raise CandidateReviewNotFoundError("candidate review not found")
        now = _now()
        capped_error = (error_message or "backtest submission failed")[
            :_MAX_ERROR_LENGTH
        ]
        if backtest_job_run_id is not None:
            review_repo.mark_backtest_submitted(
                review,
                backtest_job_run_id=backtest_job_run_id,
                updated_at=now,
            )
            job = job_repo.get(backtest_job_run_id)
            if job is not None:
                job_repo.mark_failed(
                    job,
                    capped_error,
                    finished_at=now,
                    duration_ms=0,
                )
        review_repo.mark_backtest_failed(
            review,
            error_message=capped_error,
            updated_at=now,
        )
        session.expunge(review)
        return review


def _raise_approval_conflict(status: str) -> None:
    if status == STATUS_REJECTED:
        raise CandidateReviewConflictError("candidate already rejected")
    if status in _SUBMITTED_STATUSES:
        raise CandidateReviewConflictError("candidate already submitted")
    raise CandidateReviewConflictError("candidate already submitted")


def _required_text(value: Any, message: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise CandidateReviewValidationError(message)
    return text


def _clean_operator(value: str) -> str:
    return str(value or "").strip()[:_MAX_OPERATOR_LENGTH]


def _clean_note(value: str) -> str:
    return str(value or "").strip()[:_MAX_NOTE_LENGTH]


def _now() -> datetime:
    return utcnow()


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    )


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _strict_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CandidateReviewValidationError("invalid JSON payload") from exc
    if not isinstance(parsed, dict):
        raise CandidateReviewValidationError("invalid JSON payload")
    return parsed


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
