from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import json
import time
from typing import Any, Generic, TypeVar

from sqlalchemy import Engine

from quant_trading.security import sanitize_error_message
from quant_trading.storage.db import session_scope
from quant_trading.storage.repositories import WorkflowRunRepository

T = TypeVar("T")


@dataclass(frozen=True)
class WorkflowCommandExecution(Generic[T]):
    result: T
    workflow_run_id: int


COMMAND_CREATED_OBJECTS = {
    "backtest_ma_cross": ("backtest_run", "run_id"),
    "paper_create_account": ("paper_account", "account_id"),
    "paper_start_ma_cross_run": ("paper_run", "run_id"),
    "paper_run_tick": ("paper_run", "run_id"),
}


class WorkflowCommandRunner:
    def __init__(self, engine: Engine):
        self.engine = engine

    def run(
        self,
        command_name: str,
        request_payload: dict[str, Any],
        callback: Callable[[], T],
    ) -> T:
        return self.run_with_audit(command_name, request_payload, callback).result

    def run_with_audit(
        self,
        command_name: str,
        request_payload: dict[str, Any],
        callback: Callable[[], T],
    ) -> WorkflowCommandExecution[T]:
        started_at = _utcnow()
        started_counter = time.perf_counter()
        with session_scope(self.engine) as session:
            run = WorkflowRunRepository(session).create_running(
                command_name=command_name,
                request_payload=workflow_payload_dumps(request_payload),
                started_at=started_at,
            )
            workflow_run_id = run.id

        try:
            result = callback()
        except Exception as exc:
            finished_at = _utcnow()
            duration_ms = _duration_ms(started_counter)
            with session_scope(self.engine) as session:
                repo = WorkflowRunRepository(session)
                run = repo.get(workflow_run_id)
                if run is not None:
                    repo.mark_failed(
                        run,
                        error_message=sanitize_workflow_error(exc),
                        finished_at=finished_at,
                        duration_ms=duration_ms,
                    )
            raise

        finished_at = _utcnow()
        duration_ms = _duration_ms(started_counter)
        result_payload = result if isinstance(result, dict) else {"result": result}
        created_type, created_id = infer_created_object(command_name, result_payload)
        with session_scope(self.engine) as session:
            repo = WorkflowRunRepository(session)
            run = repo.get(workflow_run_id)
            if run is not None:
                repo.mark_succeeded(
                    run,
                    result_payload=workflow_payload_dumps(result_payload),
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    created_object_type=created_type,
                    created_object_id=created_id,
                )
        return WorkflowCommandExecution(result=result, workflow_run_id=workflow_run_id)


def infer_created_object(
    command_name: str,
    result_payload: dict[str, Any],
) -> tuple[str | None, int | None]:
    mapping = COMMAND_CREATED_OBJECTS.get(command_name)
    if not mapping:
        return None, None
    object_type, id_key = mapping
    raw_id = result_payload.get(id_key)
    return object_type, int(raw_id) if raw_id is not None else None


def workflow_payload_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True)


def sanitize_workflow_error(exc: Exception) -> str:
    return sanitize_error_message(exc)


def record_failed_workflow_command(
    engine: Engine,
    command_name: str,
    request_payload: dict[str, Any],
    error_message: str,
) -> None:
    started_at = _utcnow()
    started_counter = time.perf_counter()
    with session_scope(engine) as session:
        repo = WorkflowRunRepository(session)
        run = repo.create_running(
            command_name=command_name,
            request_payload=workflow_payload_dumps(request_payload),
            started_at=started_at,
        )
        repo.mark_failed(
            run,
            error_message=sanitize_error_message(error_message),
            finished_at=_utcnow(),
            duration_ms=_duration_ms(started_counter),
        )


def _duration_ms(started_counter: float) -> int:
    return max(0, int((time.perf_counter() - started_counter) * 1000))


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
