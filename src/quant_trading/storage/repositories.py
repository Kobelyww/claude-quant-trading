from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.storage.models import InstrumentORM, JobRunORM, MarketBarORM, WorkflowRunORM


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
