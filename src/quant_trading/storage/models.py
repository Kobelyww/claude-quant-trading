from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class InstrumentORM(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    market: Mapped[str] = mapped_column(String(32), index=True)
    asset_type: Mapped[str] = mapped_column(String(32), default="stock")
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    exchange: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bars: Mapped[list["MarketBarORM"]] = relationship(back_populates="instrument")


class MarketBarORM(Base):
    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "timestamp",
            "timeframe",
            "adjusted",
            "source",
            name="uq_market_bar_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(Date, index=True)
    timeframe: Mapped[str] = mapped_column(String(16), default="1d")
    open: Mapped[float] = mapped_column(Numeric(18, 6))
    high: Mapped[float] = mapped_column(Numeric(18, 6))
    low: Mapped[float] = mapped_column(Numeric(18, 6))
    close: Mapped[float] = mapped_column(Numeric(18, 6))
    volume: Mapped[float] = mapped_column(Numeric(24, 6))
    amount: Mapped[float | None] = mapped_column(Numeric(24, 6), nullable=True)
    adjusted: Mapped[str] = mapped_column(String(16), default="qfq")
    source: Mapped[str] = mapped_column(String(64), default="legacy")
    ingestion_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    instrument: Mapped[InstrumentORM] = relationship(back_populates="bars")


class BacktestRunORM(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    initial_cash: Mapped[float] = mapped_column(Numeric(18, 6))
    final_equity: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    status: Mapped[str] = mapped_column(String(32), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BacktestEquityPointORM(Base):
    __tablename__ = "backtest_equity_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(Date, index=True)
    equity: Mapped[float] = mapped_column(Numeric(18, 6))
    cash: Mapped[float] = mapped_column(Numeric(18, 6))
    market_value: Mapped[float] = mapped_column(Numeric(18, 6))
    drawdown: Mapped[float] = mapped_column(Numeric(18, 6))


class BacktestOrderORM(Base):
    __tablename__ = "backtest_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="filled")
    submitted_at: Mapped[datetime] = mapped_column(Date)


class BacktestFillORM(Base):
    __tablename__ = "backtest_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Numeric(18, 6))
    commission: Mapped[float] = mapped_column(Numeric(18, 6))
    slippage: Mapped[float] = mapped_column(Numeric(18, 6))
    filled_at: Mapped[datetime] = mapped_column(Date)


class PaperAccountORM(Base):
    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="Default Paper Account")
    base_currency: Mapped[str] = mapped_column(String(16), default="CNY")
    initial_cash: Mapped[float] = mapped_column(Numeric(18, 6))
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperRunORM(Base):
    __tablename__ = "paper_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    universe_config: Mapped[str] = mapped_column(String(2048), default="{}")
    strategy_config: Mapped[str] = mapped_column(String(2048), default="{}")
    risk_config: Mapped[str] = mapped_column(String(2048), default="{}")
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    last_processed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperOrderORM(Base):
    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("paper_runs.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(16))
    order_type: Mapped[str] = mapped_column(String(16), default="market")
    quantity: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    reason: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    risk_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    submitted_at: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperFillORM(Base):
    __tablename__ = "paper_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("paper_runs.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Numeric(18, 6))
    commission: Mapped[float] = mapped_column(Numeric(18, 6))
    slippage: Mapped[float] = mapped_column(Numeric(18, 6))
    filled_at: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperPositionORM(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id", name="uq_paper_position_account_instrument"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    market_price: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    realized_pnl: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    updated_at: Mapped[date] = mapped_column(Date)


class CashLedgerORM(Base):
    __tablename__ = "cash_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("paper_runs.id"), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("paper_orders.id"), nullable=True, index=True)
    fill_id: Mapped[int | None] = mapped_column(ForeignKey("paper_fills.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 6))
    cash_after: Mapped[float] = mapped_column(Numeric(18, 6))
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    occurred_at: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PortfolioSnapshotORM(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_runs.id"), nullable=True, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(Date)
    equity: Mapped[float] = mapped_column(Numeric(18, 6))
    cash: Mapped[float] = mapped_column(Numeric(18, 6))
    market_value: Mapped[float] = mapped_column(Numeric(18, 6))
    realized_pnl: Mapped[float] = mapped_column(Numeric(18, 6))
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(18, 6))
    drawdown: Mapped[float] = mapped_column(Numeric(18, 6))


class RiskDecisionORM(Base):
    __tablename__ = "risk_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_runs.id"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_orders.id"), nullable=True, index=True
    )
    decision: Mapped[str] = mapped_column(String(32))
    rule_name: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BrokerOrderEventORM(Base):
    __tablename__ = "broker_order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_runs.id"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_orders.id"), nullable=True, index=True
    )
    broker_mode: Mapped[str] = mapped_column(String(32), index=True)
    client_order_id: Mapped[str] = mapped_column(String(128), index=True)
    broker_order_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    request_payload: Mapped[str] = mapped_column(Text, default="{}")
    result_payload: Mapped[str] = mapped_column(Text, default="{}")
    message: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WorkflowRunORM(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    request_payload: Mapped[str] = mapped_column(Text, default="{}")
    result_payload: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class JobRunORM(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    request_payload: Mapped[str] = mapped_column(Text, default="{}")
    result_payload: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_runs.id"),
        nullable=True,
        index=True,
    )
    rq_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class JobEventORM(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_run_id: Mapped[int] = mapped_column(ForeignKey("job_runs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(String(512), default="")
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class JobScheduleORM(Base):
    __tablename__ = "job_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    request_payload: Mapped[str] = mapped_column(Text, default="{}")
    schedule_type: Mapped[str] = mapped_column(String(32), default="interval")
    interval_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"),
        nullable=True,
        index=True,
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lock_acquired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DataSyncRunORM(Base):
    __tablename__ = "data_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str] = mapped_column(String(32), default="a_stock")
    asset_type: Mapped[str] = mapped_column(String(32), default="stock")
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    exchange: Mapped[str] = mapped_column(String(32), default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    imported_bars: Mapped[int] = mapped_column(Integer, default=0)
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentRunORM(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    model_name: Mapped[str] = mapped_column(String(128), default="")
    request_payload: Mapped[str] = mapped_column(Text, default="{}")
    metrics_payload: Mapped[str] = mapped_column(Text, default="{}")
    result_payload: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"),
        nullable=True,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentCandidateReviewORM(Base):
    __tablename__ = "agent_candidate_reviews"
    __table_args__ = (
        UniqueConstraint(
            "source_agent_run_id",
            name="uq_agent_candidate_reviews_source_agent_run_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_agent_run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), index=True)
    candidate_payload: Mapped[str] = mapped_column(Text, default="{}")
    backtest_request_payload: Mapped[str] = mapped_column(Text, default="{}")
    operator: Mapped[str] = mapped_column(String(128), default="")
    operator_note: Mapped[str] = mapped_column(Text, default="")
    backtest_job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"),
        nullable=True,
        index=True,
    )
    backtest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("backtest_runs.id"),
        nullable=True,
        index=True,
    )
    review_agent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id"),
        nullable=True,
        index=True,
    )
    data_quality_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_quality_reports.id"),
        nullable=True,
        index=True,
    )
    research_validation_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_validation_reports.id"),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DataQualityReportORM(Base):
    __tablename__ = "data_quality_reports"
    __table_args__ = (
        Index(
            "ix_data_quality_reports_symbol_start_date_end_date",
            "symbol",
            "start_date",
            "end_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_candidate_reviews.id"),
        nullable=True,
        index=True,
    )
    backtest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("backtest_runs.id"),
        nullable=True,
        index=True,
    )
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"),
        nullable=True,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64), default="")
    adjusted: Mapped[str] = mapped_column(String(16), default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bar_count: Mapped[int] = mapped_column(Integer, default=0)
    expected_bar_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_bar_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_timestamp_count: Mapped[int] = mapped_column(Integer, default=0)
    non_positive_price_count: Mapped[int] = mapped_column(Integer, default=0)
    non_positive_volume_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_ohlc_count: Mapped[int] = mapped_column(Integer, default=0)
    stale_data: Mapped[bool] = mapped_column(Boolean, default=False)
    data_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    severity: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    findings_payload: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ResearchValidationReportORM(Base):
    __tablename__ = "research_validation_reports"
    __table_args__ = (
        UniqueConstraint(
            "candidate_review_id",
            name="uq_research_validation_reports_candidate_review_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_review_id: Mapped[int] = mapped_column(
        ForeignKey("agent_candidate_reviews.id"),
        index=True,
    )
    source_backtest_run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id"),
        index=True,
    )
    data_quality_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_quality_reports.id"),
        nullable=True,
        index=True,
    )
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"),
        nullable=True,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), index=True)
    validation_status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    readiness_floor: Mapped[str] = mapped_column(String(32), default="not_ready")
    in_sample_metrics_payload: Mapped[str] = mapped_column(Text, default="{}")
    out_of_sample_metrics_payload: Mapped[str] = mapped_column(Text, default="{}")
    walk_forward_payload: Mapped[str] = mapped_column(Text, default="{}")
    parameter_sensitivity_payload: Mapped[str] = mapped_column(Text, default="{}")
    benchmark_payload: Mapped[str] = mapped_column(Text, default="{}")
    summary_payload: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
