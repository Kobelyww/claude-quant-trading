from datetime import date, datetime
from decimal import Decimal
import json

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.execution.broker import BrokerOrderRequest, BrokerOrderResult
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    AgentRunORM,
    BrokerOrderEventORM,
    DataSyncRunORM,
    InstrumentORM,
    JobEventORM,
    JobRunORM,
    JobScheduleORM,
    MarketBarORM,
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

    def list_bars(self, symbol: str) -> list[Bar]:
        rows = self.session.scalars(
            select(MarketBarORM)
            .join(InstrumentORM)
            .where(InstrumentORM.symbol == symbol)
            .order_by(MarketBarORM.timestamp)
        ).all()
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
                adjusted=row.adjusted,
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
