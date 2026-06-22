from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.storage.models import InstrumentORM, MarketBarORM


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
