from datetime import date, datetime
from decimal import Decimal
import hashlib
import json

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_trading.core.enums import Adjustment, Market
from quant_trading.core.models import Bar
from quant_trading.execution.broker import BrokerOrderRequest, BrokerOrderResult
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    AgentRunORM,
    BrokerOrderEventORM,
    DataQualityReportORM,
    DataSyncRunORM,
    ExecutionOrderDecisionORM,
    ExecutionOrderIntentORM,
    ExecutionSafetyStateORM,
    InstrumentORM,
    JobEventORM,
    JobRunORM,
    JobScheduleORM,
    KillSwitchEventORM,
    MarketBarORM,
    OperatorApprovalRequestORM,
    ResearchValidationReportORM,
    SafetyIncidentORM,
    WorkflowRunORM,
)


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _json_dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _json_dumps_canonical(value: dict) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    )


def _ops_payload_digest(value: dict) -> str:
    return hashlib.sha256(_json_dumps_canonical(value).encode("utf-8")).hexdigest()


def _cap_text(value: str, limit: int) -> str:
    return value[:limit]


_REDACTED = "[REDACTED]"
_TRUNCATED = "[TRUNCATED]"
_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "private_key",
)
_SECRET_VALUE_MARKERS = (
    "secret",
    "token",
    "password",
    "passwd",
    "apikey",
    "api_key",
)
_OPS_PAYLOAD_MAX_LENGTH = 4096
_OPS_STRING_MAX_LENGTH = 512


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _is_secret_value(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in _SECRET_VALUE_MARKERS)


def _sanitize_json_value(value, *, secret_context: bool = False):
    if secret_context:
        return _REDACTED
    if isinstance(value, dict):
        return {
            str(key): _sanitize_json_value(
                item,
                secret_context=_is_secret_key(str(key)),
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, str) and _is_secret_value(value):
        return _REDACTED
    if isinstance(value, str) and len(value) > _OPS_STRING_MAX_LENGTH:
        return value[:_OPS_STRING_MAX_LENGTH] + _TRUNCATED
    return value


def _ops_json_dumps(value: dict, limit: int = _OPS_PAYLOAD_MAX_LENGTH) -> str:
    payload = _sanitize_json_value(value)
    dumped = _json_dumps(payload)
    if len(dumped) <= limit:
        return dumped

    bounded = {
        "truncated": True,
        "payload_preview": dumped[: max(0, limit - 64)],
        "truncated_marker": _TRUNCATED,
    }
    bounded_dumped = _json_dumps(bounded)
    if len(bounded_dumped) <= limit:
        return bounded_dumped
    return _json_dumps({"truncated": True, "truncated_marker": _TRUNCATED})[:limit]


def _broker_request_payload(request: BrokerOrderRequest) -> dict:
    return {
        "client_order_id": request.client_order_id,
        "instrument_id": request.instrument_id,
        "symbol": request.symbol,
        "side": request.side.value,
        "order_type": request.order_type.value,
        "quantity": request.quantity,
        "limit_price": request.limit_price,
        "submitted_at": request.submitted_at,
        "reason": request.reason,
    }


def _broker_result_payload(result: BrokerOrderResult) -> dict:
    payload = {
        "broker_order_id": result.broker_order_id,
        "status": result.status.value,
        "mode": result.mode.value,
        "accepted": result.accepted,
        "message": result.message[:512],
        "has_fill": result.fill is not None,
    }
    if result.fill is not None:
        payload["fill"] = {
            "instrument_id": result.fill.instrument_id,
            "symbol": result.fill.symbol,
            "side": result.fill.side.value,
            "quantity": result.fill.quantity,
            "price": result.fill.price,
            "commission": result.fill.commission,
            "slippage": result.fill.slippage,
            "filled_at": result.fill.filled_at,
        }
    return payload


class InstrumentRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_symbol(self, symbol: str) -> InstrumentORM | None:
        return self.session.scalar(
            select(InstrumentORM).where(InstrumentORM.symbol == symbol)
        )

    def upsert_symbol(
        self,
        symbol: str,
        name: str,
        market: Market,
        asset_type: str,
        currency: str,
        exchange: str,
    ) -> InstrumentORM:
        existing = self.get_by_symbol(symbol)
        if existing:
            existing.name = name
            existing.market = market.value
            existing.asset_type = asset_type
            existing.currency = currency
            existing.exchange = exchange
            self.session.flush()
            return existing

        instrument = InstrumentORM(
            symbol=symbol,
            name=name,
            market=market.value,
            asset_type=asset_type,
            currency=currency,
            exchange=exchange,
        )
        self.session.add(instrument)
        self.session.flush()
        return instrument


class MarketDataRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_daily_bar(
        self,
        instrument_id: int,
        timestamp: date,
        open: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal,
        source: str,
        adjusted: str,
    ) -> MarketBarORM:
        existing = self.session.scalar(
            select(MarketBarORM).where(
                MarketBarORM.instrument_id == instrument_id,
                MarketBarORM.timestamp == timestamp,
                MarketBarORM.timeframe == "1d",
                MarketBarORM.adjusted == adjusted,
                MarketBarORM.source == source,
            )
        )
        if existing:
            existing.open = open
            existing.high = high
            existing.low = low
            existing.close = close
            existing.volume = volume
            self.session.flush()
            return existing

        row = MarketBarORM(
            instrument_id=instrument_id,
            timestamp=timestamp,
            timeframe="1d",
            open=open,
            high=high,
            low=low,
            close=close,
            volume=volume,
            adjusted=adjusted,
            source=source,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_bars(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
        source: str | None = None,
        adjusted: str | None = None,
    ) -> list[Bar]:
        statement = (
            select(MarketBarORM)
            .join(InstrumentORM)
            .where(InstrumentORM.symbol == symbol)
            .order_by(MarketBarORM.timestamp)
        )
        if start is not None:
            statement = statement.where(MarketBarORM.timestamp >= start)
        if end is not None:
            statement = statement.where(MarketBarORM.timestamp <= end)
        if source:
            statement = statement.where(MarketBarORM.source == source)
        if adjusted:
            statement = statement.where(MarketBarORM.adjusted == adjusted)
        rows = self.session.scalars(statement).all()
        return [
            Bar(
                instrument_id=row.instrument_id,
                symbol=row.instrument.symbol,
                market=Market(row.instrument.market),
                timestamp=row.timestamp,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                source=row.source,
                adjusted=Adjustment(row.adjusted),
            )
            for row in rows
        ]


class WorkflowRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_running(
        self,
        command_name: str,
        request_payload: str,
        started_at: datetime,
    ) -> WorkflowRunORM:
        row = WorkflowRunORM(
            command_name=command_name,
            status="running",
            request_payload=request_payload,
            result_payload="{}",
            started_at=started_at,
            created_at=started_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_succeeded(
        self,
        row: WorkflowRunORM,
        result_payload: str,
        finished_at: datetime,
        duration_ms: int,
        created_object_type: str | None,
        created_object_id: int | None,
    ) -> WorkflowRunORM:
        row.status = "succeeded"
        row.result_payload = result_payload
        row.error_message = None
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        row.created_object_type = created_object_type
        row.created_object_id = created_object_id
        self.session.flush()
        return row

    def mark_failed(
        self,
        row: WorkflowRunORM,
        error_message: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> WorkflowRunORM:
        row.status = "failed"
        row.error_message = error_message
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        status: str | None = None,
        command_name: str | None = None,
        limit: int = 50,
    ) -> list[WorkflowRunORM]:
        statement = select(WorkflowRunORM).order_by(WorkflowRunORM.id.desc()).limit(limit)
        if status:
            statement = statement.where(WorkflowRunORM.status == status)
        if command_name:
            statement = statement.where(WorkflowRunORM.command_name == command_name)
        return list(self.session.scalars(statement).all())

    def get(self, workflow_run_id: int) -> WorkflowRunORM | None:
        return self.session.get(WorkflowRunORM, workflow_run_id)


class BrokerOrderEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def record_from_broker_result(
        self,
        *,
        run_id: int | None,
        order_id: int | None,
        request: BrokerOrderRequest,
        result: BrokerOrderResult,
        created_at: datetime | date,
    ) -> BrokerOrderEventORM:
        row = BrokerOrderEventORM(
            run_id=run_id,
            order_id=order_id,
            broker_mode=result.mode.value,
            client_order_id=request.client_order_id,
            broker_order_id=result.broker_order_id,
            status=result.status.value,
            accepted=result.accepted,
            request_payload=_json_dumps(_broker_request_payload(request)),
            result_payload=_json_dumps(_broker_result_payload(result)),
            message=result.message[:512],
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_for_order(self, order_id: int) -> list[BrokerOrderEventORM]:
        return list(
            self.session.scalars(
                select(BrokerOrderEventORM)
                .where(BrokerOrderEventORM.order_id == order_id)
                .order_by(BrokerOrderEventORM.id)
            ).all()
        )

    def list_for_run(self, run_id: int) -> list[BrokerOrderEventORM]:
        return list(
            self.session.scalars(
                select(BrokerOrderEventORM)
                .where(BrokerOrderEventORM.run_id == run_id)
                .order_by(BrokerOrderEventORM.id)
            ).all()
        )

    def get(self, event_id: int) -> BrokerOrderEventORM | None:
        return self.session.get(BrokerOrderEventORM, event_id)


class JobRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_queued(
        self,
        job_type: str,
        request_payload: str,
        queued_at: datetime,
    ) -> JobRunORM:
        row = JobRunORM(
            job_type=job_type,
            status="queued",
            progress=0,
            request_payload=request_payload,
            result_payload="{}",
            queued_at=queued_at,
            created_at=queued_at,
            updated_at=queued_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_enqueued(
        self,
        row: JobRunORM,
        rq_job_id: str,
        updated_at: datetime,
    ) -> JobRunORM:
        row.rq_job_id = rq_job_id
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_running(self, row: JobRunORM, started_at: datetime) -> JobRunORM:
        row.status = "running"
        row.progress = 10
        row.started_at = started_at
        row.updated_at = started_at
        self.session.flush()
        return row

    def mark_succeeded(
        self,
        row: JobRunORM,
        result_payload: str,
        workflow_run_id: int | None,
        finished_at: datetime,
        duration_ms: int,
    ) -> JobRunORM:
        row.status = "succeeded"
        row.progress = 100
        row.result_payload = result_payload
        row.error_message = None
        row.workflow_run_id = workflow_run_id
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        row.updated_at = finished_at
        self.session.flush()
        return row

    def mark_failed(
        self,
        row: JobRunORM,
        error_message: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> JobRunORM:
        row.status = "failed"
        row.error_message = error_message
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        row.updated_at = finished_at
        self.session.flush()
        return row

    def update_progress(
        self,
        row: JobRunORM,
        progress: int,
        updated_at: datetime,
    ) -> JobRunORM:
        row.progress = progress
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_cancel_requested(
        self,
        row: JobRunORM,
        updated_at: datetime,
    ) -> JobRunORM:
        row.status = "cancel_requested"
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_cancelled(
        self,
        row: JobRunORM,
        finished_at: datetime,
        duration_ms: int | None = None,
    ) -> JobRunORM:
        row.status = "cancelled"
        row.error_message = "cancelled"
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        row.updated_at = finished_at
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[JobRunORM]:
        statement = select(JobRunORM).order_by(JobRunORM.id.desc()).limit(limit)
        if status:
            statement = statement.where(JobRunORM.status == status)
        if job_type:
            statement = statement.where(JobRunORM.job_type == job_type)
        return list(self.session.scalars(statement).all())

    def get(self, job_run_id: int) -> JobRunORM | None:
        return self.session.get(JobRunORM, job_run_id)


class JobEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        job_run_id: int,
        event_type: str,
        message: str = "",
        *,
        progress: int | None = None,
        payload: dict | None = None,
        created_at: datetime,
    ) -> JobEventORM:
        row = JobEventORM(
            job_run_id=job_run_id,
            event_type=event_type,
            message=message,
            progress=progress,
            payload=json.dumps(payload or {}, sort_keys=True),
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

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

    def list_recent(self, *, limit: int = 50) -> list[JobEventORM]:
        return list(
            self.session.scalars(
                select(JobEventORM).order_by(JobEventORM.id.desc()).limit(limit)
            ).all()
        )


class JobScheduleRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        name: str,
        job_type: str,
        request_payload: str,
        schedule_type: str,
        interval_seconds: int,
        enabled: bool,
        next_run_at: datetime,
        created_at: datetime,
    ) -> JobScheduleORM:
        row = JobScheduleORM(
            name=name,
            job_type=job_type,
            request_payload=request_payload,
            schedule_type=schedule_type,
            interval_seconds=interval_seconds,
            enabled=enabled,
            next_run_at=next_run_at,
            created_at=created_at,
            updated_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def update(
        self,
        row: JobScheduleORM,
        *,
        enabled: bool | None = None,
        request_payload: str | None = None,
        interval_seconds: int | None = None,
        next_run_at: datetime | None = None,
        updated_at: datetime,
    ) -> JobScheduleORM:
        if enabled is not None:
            row.enabled = enabled
        if request_payload is not None:
            row.request_payload = request_payload
        if interval_seconds is not None:
            row.interval_seconds = interval_seconds
        if next_run_at is not None:
            row.next_run_at = next_run_at
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_submitted(
        self,
        row: JobScheduleORM,
        job_run_id: int,
        ran_at: datetime,
        next_run_at: datetime,
    ) -> JobScheduleORM:
        row.last_run_at = ran_at
        row.last_job_run_id = job_run_id
        row.next_run_at = next_run_at
        row.locked_until = None
        row.locked_by = None
        row.lock_acquired_at = None
        row.updated_at = ran_at
        self.session.flush()
        return row

    def acquire_due_lease(
        self,
        schedule_id: int,
        *,
        now: datetime,
        lease_until: datetime,
        locked_by: str,
    ) -> bool:
        result = self.session.execute(
            update(JobScheduleORM)
            .where(JobScheduleORM.id == schedule_id)
            .where(JobScheduleORM.enabled.is_(True))
            .where(JobScheduleORM.next_run_at <= now)
            .where(
                or_(
                    JobScheduleORM.locked_until.is_(None),
                    JobScheduleORM.locked_until <= now,
                )
            )
            .values(
                locked_until=lease_until,
                locked_by=locked_by[:128],
                lock_acquired_at=now,
                updated_at=now,
            )
        )
        self.session.flush()
        return result.rowcount == 1

    def clear_lease(self, row: JobScheduleORM, updated_at: datetime) -> JobScheduleORM:
        row.locked_until = None
        row.locked_by = None
        row.lock_acquired_at = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def list_due(self, now: datetime) -> list[JobScheduleORM]:
        return list(
            self.session.scalars(
                select(JobScheduleORM)
                .where(JobScheduleORM.enabled.is_(True))
                .where(JobScheduleORM.next_run_at <= now)
                .where(
                    or_(
                        JobScheduleORM.locked_until.is_(None),
                        JobScheduleORM.locked_until <= now,
                    )
                )
                .order_by(JobScheduleORM.next_run_at, JobScheduleORM.id)
            ).all()
        )

    def list_recent(
        self,
        *,
        enabled: bool | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[JobScheduleORM]:
        statement = select(JobScheduleORM).order_by(JobScheduleORM.id.desc()).limit(limit)
        if enabled is not None:
            statement = statement.where(JobScheduleORM.enabled.is_(enabled))
        if job_type:
            statement = statement.where(JobScheduleORM.job_type == job_type)
        return list(self.session.scalars(statement).all())

    def get(self, schedule_id: int) -> JobScheduleORM | None:
        return self.session.get(JobScheduleORM, schedule_id)

    def get_by_name(self, name: str) -> JobScheduleORM | None:
        return self.session.scalar(select(JobScheduleORM).where(JobScheduleORM.name == name))


class DataSyncRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_running(
        self,
        provider: str,
        symbol: str,
        market: str,
        asset_type: str,
        currency: str,
        exchange: str,
        start_date: date | None,
        end_date: date | None,
        job_run_id: int | None,
        started_at: datetime,
    ) -> DataSyncRunORM:
        row = DataSyncRunORM(
            provider=provider,
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            currency=currency,
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
            status="running",
            imported_bars=0,
            job_run_id=job_run_id,
            started_at=started_at,
            created_at=started_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_succeeded(
        self,
        row: DataSyncRunORM,
        imported_bars: int,
        finished_at: datetime,
        duration_ms: int,
    ) -> DataSyncRunORM:
        row.status = "succeeded"
        row.imported_bars = imported_bars
        row.error_message = None
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def mark_failed(
        self,
        row: DataSyncRunORM,
        error_message: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> DataSyncRunORM:
        row.status = "failed"
        row.error_message = error_message
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        provider: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[DataSyncRunORM]:
        statement = select(DataSyncRunORM).order_by(DataSyncRunORM.id.desc()).limit(limit)
        if provider:
            statement = statement.where(DataSyncRunORM.provider == provider)
        if symbol:
            statement = statement.where(DataSyncRunORM.symbol == symbol)
        if status:
            statement = statement.where(DataSyncRunORM.status == status)
        return list(self.session.scalars(statement).all())

    def get(self, sync_run_id: int) -> DataSyncRunORM | None:
        return self.session.get(DataSyncRunORM, sync_run_id)


class AgentRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_running(
        self,
        *,
        agent_type: str,
        symbol: str | None,
        model_name: str,
        request_payload: str,
        job_run_id: int | None,
        started_at: datetime,
    ) -> AgentRunORM:
        row = AgentRunORM(
            agent_type=agent_type,
            status="running",
            symbol=symbol,
            model_name=model_name,
            request_payload=request_payload,
            metrics_payload="{}",
            result_payload="{}",
            error_message=None,
            job_run_id=job_run_id,
            started_at=started_at,
            created_at=started_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_succeeded(
        self,
        row: AgentRunORM,
        *,
        metrics_payload: str,
        result_payload: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> AgentRunORM:
        row.status = "succeeded"
        row.metrics_payload = metrics_payload
        row.result_payload = result_payload
        row.error_message = None
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def mark_failed(
        self,
        row: AgentRunORM,
        error_message: str,
        *,
        finished_at: datetime,
        duration_ms: int,
    ) -> AgentRunORM:
        row.status = "failed"
        row.error_message = error_message[:1000]
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        agent_type: str | None = None,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[AgentRunORM]:
        statement = select(AgentRunORM).order_by(AgentRunORM.id.desc()).limit(limit)
        if agent_type:
            statement = statement.where(AgentRunORM.agent_type == agent_type)
        if status:
            statement = statement.where(AgentRunORM.status == status)
        if symbol:
            statement = statement.where(AgentRunORM.symbol == symbol)
        return list(self.session.scalars(statement).all())

    def get(self, agent_run_id: int) -> AgentRunORM | None:
        return self.session.get(AgentRunORM, agent_run_id)


class AgentCandidateReviewRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_decision(
        self,
        *,
        source_agent_run_id: int,
        status: str,
        symbol: str,
        strategy_name: str,
        candidate_payload: str,
        backtest_request_payload: str,
        operator: str,
        operator_note: str,
        decided_at: datetime | None,
        created_at: datetime,
    ) -> AgentCandidateReviewORM:
        row = AgentCandidateReviewORM(
            source_agent_run_id=source_agent_run_id,
            status=status,
            symbol=symbol,
            strategy_name=strategy_name,
            candidate_payload=candidate_payload,
            backtest_request_payload=backtest_request_payload,
            operator=operator,
            operator_note=operator_note,
            decided_at=decided_at,
            created_at=created_at,
            updated_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_backtest_submitted(
        self,
        row: AgentCandidateReviewORM,
        *,
        backtest_job_run_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "backtest_submitted"
        row.backtest_job_run_id = backtest_job_run_id
        row.error_message = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_backtest_succeeded(
        self,
        row: AgentCandidateReviewORM,
        *,
        backtest_run_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "backtest_succeeded"
        row.backtest_run_id = backtest_run_id
        row.error_message = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_backtest_failed(
        self,
        row: AgentCandidateReviewORM,
        *,
        error_message: str,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "backtest_failed"
        row.error_message = error_message[:1000]
        row.updated_at = updated_at
        self.session.flush()
        return row

    def update_rejection(
        self,
        row: AgentCandidateReviewORM,
        *,
        candidate_payload: str,
        backtest_request_payload: str,
        operator: str,
        operator_note: str,
        decided_at: datetime,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "rejected"
        row.candidate_payload = candidate_payload
        row.backtest_request_payload = backtest_request_payload
        row.operator = operator
        row.operator_note = operator_note
        row.decided_at = decided_at
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_review_requested(
        self,
        row: AgentCandidateReviewORM,
        *,
        review_agent_run_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "review_requested"
        row.review_agent_run_id = review_agent_run_id
        row.error_message = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_review_succeeded(
        self,
        row: AgentCandidateReviewORM,
        *,
        review_agent_run_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "review_succeeded"
        row.review_agent_run_id = review_agent_run_id
        row.error_message = None
        row.updated_at = updated_at
        self.session.flush()
        return row

    def mark_review_failed(
        self,
        row: AgentCandidateReviewORM,
        *,
        review_agent_run_id: int,
        error_message: str,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.status = "review_failed"
        row.review_agent_run_id = review_agent_run_id
        row.error_message = error_message[:1000]
        row.updated_at = updated_at
        self.session.flush()
        return row

    def link_data_quality_report(
        self,
        row: AgentCandidateReviewORM,
        *,
        data_quality_report_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.data_quality_report_id = data_quality_report_id
        row.updated_at = updated_at
        self.session.flush()
        return row

    def link_research_validation_report(
        self,
        row: AgentCandidateReviewORM,
        *,
        research_validation_report_id: int,
        updated_at: datetime,
    ) -> AgentCandidateReviewORM:
        row.research_validation_report_id = research_validation_report_id
        row.updated_at = updated_at
        self.session.flush()
        return row

    def get(self, review_id: int) -> AgentCandidateReviewORM | None:
        return self.session.get(AgentCandidateReviewORM, review_id)

    def get_by_source_agent_run_id(
        self,
        source_agent_run_id: int,
    ) -> AgentCandidateReviewORM | None:
        return self.session.scalar(
            select(AgentCandidateReviewORM).where(
                AgentCandidateReviewORM.source_agent_run_id == source_agent_run_id
            )
        )

    def list_recent(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
        strategy_name: str | None = None,
        limit: int = 50,
    ) -> list[AgentCandidateReviewORM]:
        statement = select(AgentCandidateReviewORM).order_by(
            AgentCandidateReviewORM.id.desc()
        ).limit(limit)
        if status:
            statement = statement.where(AgentCandidateReviewORM.status == status)
        if symbol:
            statement = statement.where(AgentCandidateReviewORM.symbol == symbol)
        if strategy_name:
            statement = statement.where(
                AgentCandidateReviewORM.strategy_name == strategy_name
            )
        return list(self.session.scalars(statement).all())


class DataQualityReportRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_running(
        self,
        *,
        candidate_review_id: int | None,
        backtest_run_id: int | None,
        job_run_id: int | None,
        symbol: str,
        source: str,
        adjusted: str,
        start_date: date | None,
        end_date: date | None,
        created_at: datetime,
    ) -> DataQualityReportORM:
        row = DataQualityReportORM(
            candidate_review_id=candidate_review_id,
            backtest_run_id=backtest_run_id,
            job_run_id=job_run_id,
            symbol=symbol,
            source=source,
            adjusted=adjusted,
            start_date=start_date,
            end_date=end_date,
            bar_count=0,
            expected_bar_count=0,
            missing_bar_count=0,
            duplicate_timestamp_count=0,
            non_positive_price_count=0,
            non_positive_volume_count=0,
            invalid_ohlc_count=0,
            stale_data=False,
            data_fingerprint="",
            status="running",
            severity="unknown",
            findings_payload="{}",
            error_message=None,
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_completed(
        self,
        row: DataQualityReportORM,
        *,
        status: str,
        severity: str,
        bar_count: int,
        expected_bar_count: int,
        missing_bar_count: int,
        duplicate_timestamp_count: int,
        non_positive_price_count: int,
        non_positive_volume_count: int,
        invalid_ohlc_count: int,
        stale_data: bool,
        data_fingerprint: str,
        findings_payload: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> DataQualityReportORM:
        row.status = status
        row.severity = severity
        row.bar_count = bar_count
        row.expected_bar_count = expected_bar_count
        row.missing_bar_count = missing_bar_count
        row.duplicate_timestamp_count = duplicate_timestamp_count
        row.non_positive_price_count = non_positive_price_count
        row.non_positive_volume_count = non_positive_volume_count
        row.invalid_ohlc_count = invalid_ohlc_count
        row.stale_data = stale_data
        row.data_fingerprint = data_fingerprint
        row.findings_payload = findings_payload
        row.error_message = None
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def mark_failed(
        self,
        row: DataQualityReportORM,
        error_message: str,
        *,
        finished_at: datetime,
        duration_ms: int,
    ) -> DataQualityReportORM:
        row.status = "failed"
        row.severity = "high"
        row.error_message = error_message[:1000]
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        candidate_review_id: int | None = None,
        symbol: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[DataQualityReportORM]:
        statement = select(DataQualityReportORM).order_by(
            DataQualityReportORM.id.desc()
        ).limit(limit)
        if candidate_review_id is not None:
            statement = statement.where(
                DataQualityReportORM.candidate_review_id == candidate_review_id
            )
        if symbol:
            statement = statement.where(DataQualityReportORM.symbol == symbol)
        if status:
            statement = statement.where(DataQualityReportORM.status == status)
        if severity:
            statement = statement.where(DataQualityReportORM.severity == severity)
        return list(self.session.scalars(statement).all())

    def get(self, report_id: int) -> DataQualityReportORM | None:
        return self.session.get(DataQualityReportORM, report_id)


class ResearchValidationReportRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_or_reset_running(
        self,
        *,
        candidate_review_id: int,
        source_backtest_run_id: int,
        data_quality_report_id: int | None,
        job_run_id: int | None,
        symbol: str,
        strategy_name: str,
        started_at: datetime,
    ) -> ResearchValidationReportORM:
        row = self.get_by_candidate_review_id(candidate_review_id)
        if row is None:
            row = ResearchValidationReportORM(candidate_review_id=candidate_review_id)
            self.session.add(row)

        row.source_backtest_run_id = source_backtest_run_id
        row.data_quality_report_id = data_quality_report_id
        row.job_run_id = job_run_id
        row.symbol = symbol
        row.strategy_name = strategy_name
        row.validation_status = "running"
        row.readiness_floor = "not_ready"
        row.in_sample_metrics_payload = "{}"
        row.out_of_sample_metrics_payload = "{}"
        row.walk_forward_payload = "{}"
        row.parameter_sensitivity_payload = "{}"
        row.benchmark_payload = "{}"
        row.summary_payload = "{}"
        row.error_message = None
        row.created_at = started_at
        row.finished_at = None
        row.duration_ms = None
        self.session.flush()
        return row

    def mark_completed(
        self,
        row: ResearchValidationReportORM,
        *,
        validation_status: str,
        readiness_floor: str,
        data_quality_report_id: int | None,
        in_sample_metrics_payload: str,
        out_of_sample_metrics_payload: str,
        walk_forward_payload: str,
        parameter_sensitivity_payload: str,
        benchmark_payload: str,
        summary_payload: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> ResearchValidationReportORM:
        row.validation_status = validation_status
        row.readiness_floor = readiness_floor
        row.data_quality_report_id = data_quality_report_id
        row.in_sample_metrics_payload = in_sample_metrics_payload
        row.out_of_sample_metrics_payload = out_of_sample_metrics_payload
        row.walk_forward_payload = walk_forward_payload
        row.parameter_sensitivity_payload = parameter_sensitivity_payload
        row.benchmark_payload = benchmark_payload
        row.summary_payload = summary_payload
        row.error_message = None
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def mark_failed(
        self,
        row: ResearchValidationReportORM,
        error_message: str,
        *,
        finished_at: datetime,
        duration_ms: int,
    ) -> ResearchValidationReportORM:
        row.validation_status = "failed"
        row.readiness_floor = "not_ready"
        row.error_message = error_message[:1000]
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        candidate_review_id: int | None = None,
        symbol: str | None = None,
        validation_status: str | None = None,
        limit: int = 50,
    ) -> list[ResearchValidationReportORM]:
        statement = select(ResearchValidationReportORM).order_by(
            ResearchValidationReportORM.id.desc()
        ).limit(limit)
        if candidate_review_id is not None:
            statement = statement.where(
                ResearchValidationReportORM.candidate_review_id == candidate_review_id
            )
        if symbol:
            statement = statement.where(ResearchValidationReportORM.symbol == symbol)
        if validation_status:
            statement = statement.where(
                ResearchValidationReportORM.validation_status == validation_status
            )
        return list(self.session.scalars(statement).all())

    def get(self, report_id: int) -> ResearchValidationReportORM | None:
        return self.session.get(ResearchValidationReportORM, report_id)

    def get_by_candidate_review_id(
        self,
        candidate_review_id: int,
    ) -> ResearchValidationReportORM | None:
        return self.session.scalar(
            select(ResearchValidationReportORM).where(
                ResearchValidationReportORM.candidate_review_id == candidate_review_id
            )
        )


def _normalize_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def _order_intent_comparison_payload(
    *,
    source_type: str,
    source_id: int | None,
    paper_run_id: int | None,
    paper_order_id: int | None,
    client_order_id: str,
    symbol: str,
    instrument_id: int,
    side: str,
    order_type: str,
    quantity: int,
    limit_price,
    estimated_price,
    estimated_notional,
    broker_mode: str,
    risk_profile_name: str,
    risk_summary_payload_digest: str,
) -> dict:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "paper_run_id": paper_run_id,
        "paper_order_id": paper_order_id,
        "client_order_id": client_order_id,
        "symbol": symbol,
        "instrument_id": instrument_id,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
        "limit_price": _normalize_decimal(limit_price),
        "estimated_price": _normalize_decimal(estimated_price),
        "estimated_notional": _normalize_decimal(estimated_notional),
        "broker_mode": broker_mode,
        "risk_profile_name": risk_profile_name,
        "risk_summary_payload_digest": risk_summary_payload_digest,
    }


def _order_intent_row_payload(row: ExecutionOrderIntentORM) -> dict:
    return _order_intent_comparison_payload(
        source_type=row.source_type,
        source_id=row.source_id,
        paper_run_id=row.paper_run_id,
        paper_order_id=row.paper_order_id,
        client_order_id=row.client_order_id,
        symbol=row.symbol,
        instrument_id=row.instrument_id,
        side=row.side,
        order_type=row.order_type,
        quantity=row.quantity,
        limit_price=row.limit_price,
        estimated_price=row.estimated_price,
        estimated_notional=row.estimated_notional,
        broker_mode=row.broker_mode,
        risk_profile_name=row.risk_profile_name,
        risk_summary_payload_digest=row.risk_summary_payload_digest,
    )


def _raise_if_order_intent_conflicts(
    row: ExecutionOrderIntentORM,
    expected_payload: dict,
) -> None:
    if _order_intent_row_payload(row) != expected_payload:
        raise ValueError("client_order_id already exists with different payload")


class ExecutionSafetyStateRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_global(self) -> ExecutionSafetyStateORM | None:
        return self.session.scalar(
            select(ExecutionSafetyStateORM).where(ExecutionSafetyStateORM.scope == "global")
        )

    def get_or_create_global(self, now: datetime) -> ExecutionSafetyStateORM:
        row = self.get_global()
        if row is not None:
            return row

        row = ExecutionSafetyStateORM(
            scope="global",
            kill_switch_active=False,
            dry_run_enabled=True,
            simulated_enabled=True,
            live_enabled=False,
            reason="default simulated and dry-run startup",
            updated_by="system",
            updated_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def set_kill_switch(
        self,
        active: bool,
        operator: str,
        reason: str,
        now: datetime,
    ) -> ExecutionSafetyStateORM:
        row = self.get_or_create_global(now)
        row.kill_switch_active = active
        row.reason = _cap_text(reason, 1024)
        row.updated_by = _cap_text(operator, 128)
        row.updated_at = now
        self.session.flush()
        return row

    def payload(self, row: ExecutionSafetyStateORM) -> dict:
        return {
            "scope": row.scope,
            "kill_switch_active": row.kill_switch_active,
            "dry_run_enabled": row.dry_run_enabled,
            "simulated_enabled": row.simulated_enabled,
            "live_enabled": row.live_enabled,
            "reason": row.reason,
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat(),
        }


class ExecutionOrderIntentRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, order_intent_id: int) -> ExecutionOrderIntentORM | None:
        return self.session.get(ExecutionOrderIntentORM, order_intent_id)

    def get_by_client_order_id(
        self,
        client_order_id: str,
    ) -> ExecutionOrderIntentORM | None:
        return self.session.scalar(
            select(ExecutionOrderIntentORM).where(
                ExecutionOrderIntentORM.client_order_id == client_order_id
            )
        )

    def get_or_create(
        self,
        *,
        source_type: str,
        source_id: int | None,
        paper_run_id: int | None,
        paper_order_id: int | None,
        client_order_id: str,
        symbol: str,
        instrument_id: int,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: Decimal | None,
        estimated_price: Decimal | None,
        estimated_notional: Decimal,
        broker_mode: str,
        risk_profile_name: str,
        risk_summary_payload: dict,
        approval_required: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> tuple[ExecutionOrderIntentORM, bool]:
        payload_json = _ops_json_dumps(risk_summary_payload)
        payload_digest = _ops_payload_digest(risk_summary_payload)
        expected_payload = _order_intent_comparison_payload(
            source_type=source_type,
            source_id=source_id,
            paper_run_id=paper_run_id,
            paper_order_id=paper_order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            instrument_id=instrument_id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            estimated_price=estimated_price,
            estimated_notional=estimated_notional,
            broker_mode=broker_mode,
            risk_profile_name=risk_profile_name,
            risk_summary_payload_digest=payload_digest,
        )
        existing = self.get_by_client_order_id(client_order_id)
        if existing is not None:
            _raise_if_order_intent_conflicts(existing, expected_payload)
            return existing, False

        row = ExecutionOrderIntentORM(
            source_type=source_type,
            source_id=source_id,
            paper_run_id=paper_run_id,
            paper_order_id=paper_order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            instrument_id=instrument_id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            estimated_price=estimated_price,
            estimated_notional=estimated_notional,
            broker_mode=broker_mode,
            status="created",
            risk_profile_name=risk_profile_name,
            risk_summary_payload=payload_json,
            risk_summary_payload_digest=payload_digest,
            approval_required=approval_required,
            created_at=created_at,
            updated_at=updated_at,
        )
        try:
            with self.session.begin_nested():
                self.session.add(row)
                self.session.flush()
            return row, True
        except IntegrityError:
            existing = self.get_by_client_order_id(client_order_id)
            if existing is None:
                raise
            _raise_if_order_intent_conflicts(existing, expected_payload)
            return existing, False

    def set_status(
        self,
        row: ExecutionOrderIntentORM,
        status: str,
        updated_at: datetime,
        *,
        approval_required: bool | None = None,
        approval_request_id: int | None = None,
        blocked_reason_code: str | None = None,
        blocked_reason: str | None = None,
        submitted_at: datetime | None = None,
    ) -> ExecutionOrderIntentORM:
        row.status = status
        row.updated_at = updated_at
        if approval_required is not None:
            row.approval_required = approval_required
        if approval_request_id is not None:
            row.approval_request_id = approval_request_id
        if blocked_reason_code is not None:
            row.blocked_reason_code = blocked_reason_code
        if blocked_reason is not None:
            row.blocked_reason = _cap_text(blocked_reason, 1024)
        if submitted_at is not None:
            row.submitted_at = submitted_at
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        status: str | None = None,
        broker_mode: str | None = None,
        limit: int = 50,
    ) -> list[ExecutionOrderIntentORM]:
        statement = select(ExecutionOrderIntentORM).order_by(
            ExecutionOrderIntentORM.id.desc()
        ).limit(limit)
        if status:
            statement = statement.where(ExecutionOrderIntentORM.status == status)
        if broker_mode:
            statement = statement.where(ExecutionOrderIntentORM.broker_mode == broker_mode)
        return list(self.session.scalars(statement).all())


class ExecutionOrderDecisionRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        order_intent_id: int,
        decision_type: str,
        reason_code: str,
        message: str,
        policy_payload: dict,
        created_at: datetime,
    ) -> ExecutionOrderDecisionORM:
        row = ExecutionOrderDecisionORM(
            order_intent_id=order_intent_id,
            decision_type=decision_type,
            reason_code=reason_code,
            message=_cap_text(message, 1024),
            policy_payload=_ops_json_dumps(policy_payload),
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_recent(self, *, limit: int = 50) -> list[ExecutionOrderDecisionORM]:
        return list(
            self.session.scalars(
                select(ExecutionOrderDecisionORM)
                .order_by(ExecutionOrderDecisionORM.id.desc())
                .limit(limit)
            ).all()
        )


class OperatorApprovalRequestRepository:
    _DECISION_STATUSES = frozenset({"approved", "rejected", "expired", "cancelled"})

    def __init__(self, session: Session):
        self.session = session

    def get(self, approval_request_id: int) -> OperatorApprovalRequestORM | None:
        return self.session.get(OperatorApprovalRequestORM, approval_request_id)

    def get_active_for_resource(
        self,
        resource_type: str,
        resource_id: int,
    ) -> OperatorApprovalRequestORM | None:
        return self.session.scalar(
            select(OperatorApprovalRequestORM).where(
                OperatorApprovalRequestORM.resource_type == resource_type,
                OperatorApprovalRequestORM.resource_id == resource_id,
                OperatorApprovalRequestORM.status == "pending",
            )
        )

    def create_pending(
        self,
        resource_type: str,
        resource_id: int,
        reason_code: str,
        requested_by: str,
        requested_at: datetime,
        expires_at: datetime | None,
    ) -> OperatorApprovalRequestORM:
        return self.get_or_create_active(
            resource_type=resource_type,
            resource_id=resource_id,
            reason_code=reason_code,
            requested_by=requested_by,
            requested_at=requested_at,
            expires_at=expires_at,
        )

    def get_or_create_active(
        self,
        resource_type: str,
        resource_id: int,
        reason_code: str,
        requested_by: str,
        requested_at: datetime,
        expires_at: datetime | None,
    ) -> OperatorApprovalRequestORM:
        existing = self.get_active_for_resource(resource_type, resource_id)
        if existing is not None:
            return existing

        row = OperatorApprovalRequestORM(
            resource_type=resource_type,
            resource_id=resource_id,
            status="pending",
            reason_code=reason_code,
            requested_by=_cap_text(requested_by, 128),
            requested_at=requested_at,
            expires_at=expires_at,
        )
        try:
            with self.session.begin_nested():
                self.session.add(row)
                self.session.flush()
            return row
        except IntegrityError:
            existing = self.get_active_for_resource(resource_type, resource_id)
            if existing is None:
                raise
            return existing

    def decide(
        self,
        row: OperatorApprovalRequestORM,
        status: str,
        operator: str,
        note: str,
        decided_at: datetime,
    ) -> OperatorApprovalRequestORM:
        if row.status != "pending":
            raise ValueError("approval request is not pending")
        if status not in self._DECISION_STATUSES:
            raise ValueError(f"invalid approval decision status: {status}")
        row.status = status
        row.decided_by = _cap_text(operator, 128)
        row.operator_note = _cap_text(note, 2048)
        row.decided_at = decided_at
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[OperatorApprovalRequestORM]:
        statement = select(OperatorApprovalRequestORM).order_by(
            OperatorApprovalRequestORM.id.desc()
        ).limit(limit)
        if status:
            statement = statement.where(OperatorApprovalRequestORM.status == status)
        return list(self.session.scalars(statement).all())


class SafetyIncidentRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, incident_id: int) -> SafetyIncidentORM | None:
        return self.session.get(SafetyIncidentORM, incident_id)

    def create(
        self,
        severity: str,
        category: str,
        resource_type: str | None,
        resource_id: int | None,
        reason_code: str,
        message: str,
        payload: dict,
        created_at: datetime,
    ) -> SafetyIncidentORM:
        row = SafetyIncidentORM(
            severity=severity,
            category=category,
            status="open",
            resource_type=resource_type,
            resource_id=resource_id,
            reason_code=reason_code,
            message=_cap_text(message, 2048),
            payload=_ops_json_dumps(payload),
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def acknowledge(
        self,
        row: SafetyIncidentORM,
        operator: str,
        acknowledged_at: datetime,
    ) -> SafetyIncidentORM:
        if row.status == "resolved":
            raise ValueError("incident is already resolved")
        row.status = "acknowledged"
        row.acknowledged_by = _cap_text(operator, 128)
        row.acknowledged_at = acknowledged_at
        self.session.flush()
        return row

    def resolve(
        self,
        row: SafetyIncidentORM,
        operator: str,
        resolved_at: datetime,
    ) -> SafetyIncidentORM:
        row.status = "resolved"
        row.resolved_by = _cap_text(operator, 128)
        row.resolved_at = resolved_at
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[SafetyIncidentORM]:
        statement = select(SafetyIncidentORM).order_by(
            SafetyIncidentORM.id.desc()
        ).limit(limit)
        if status:
            statement = statement.where(SafetyIncidentORM.status == status)
        if severity:
            statement = statement.where(SafetyIncidentORM.severity == severity)
        return list(self.session.scalars(statement).all())


class KillSwitchEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        scope: str,
        previous_state_payload: dict,
        new_state_payload: dict,
        operator: str,
        reason: str,
        created_at: datetime,
    ) -> KillSwitchEventORM:
        row = KillSwitchEventORM(
            scope=scope,
            previous_state_payload=_ops_json_dumps(previous_state_payload),
            new_state_payload=_ops_json_dumps(new_state_payload),
            operator=_cap_text(operator, 128),
            reason=_cap_text(reason, 1024),
            created_at=created_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_recent(self, *, limit: int = 50) -> list[KillSwitchEventORM]:
        return list(
            self.session.scalars(
                select(KillSwitchEventORM)
                .order_by(KillSwitchEventORM.id.desc())
                .limit(limit)
            ).all()
        )
