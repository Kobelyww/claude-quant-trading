from datetime import datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
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
