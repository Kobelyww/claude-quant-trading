from __future__ import annotations

from datetime import UTC, date, datetime
import time
from typing import Any

from sqlalchemy import Engine

from quant_trading.core.enums import Market
from quant_trading.core.models import Bar
from quant_trading.data.providers.registry import ProviderRegistry, build_default_provider_registry
from quant_trading.data.validation import validate_bars
from quant_trading.storage.db import session_scope
from quant_trading.storage.repositories import (
    DataSyncRunRepository,
    InstrumentRepository,
    MarketDataRepository,
)


def sync_daily_market_data(
    engine: Engine,
    provider_name: str,
    symbol: str,
    start: str | date | None,
    end: str | date | None,
    *,
    registry: ProviderRegistry | None = None,
    job_run_id: int | None = None,
) -> dict[str, Any]:
    provider_name = _normalize_provider_name(provider_name)
    symbol = _normalize_symbol(symbol)
    start_date = _parse_date(start, "start")
    end_date = _parse_date(end, "end")
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    registry = registry or build_default_provider_registry()
    provider = registry.get(provider_name)
    exchange = _derive_exchange(symbol)
    market = Market.A_STOCK.value
    asset_type = "stock"
    currency = "CNY"
    started_at = _utcnow()
    started_counter = time.perf_counter()

    with session_scope(engine) as session:
        sync_repo = DataSyncRunRepository(session)
        sync_run = sync_repo.create_running(
            provider=provider_name,
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            currency=currency,
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
            job_run_id=job_run_id,
            started_at=started_at,
        )
        instrument = InstrumentRepository(session).upsert_symbol(
            symbol=symbol,
            name=symbol,
            market=Market.A_STOCK,
            asset_type=asset_type,
            currency=currency,
            exchange=exchange,
        )
        sync_run_id = sync_run.id
        instrument_id = instrument.id

    try:
        bars = validate_bars(
            [
                _normalize_bar(instrument_id, symbol, bar)
                for bar in provider.fetch_daily_bars(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    start=start_date.isoformat() if start_date else None,
                    end=end_date.isoformat() if end_date else None,
                )
            ]
        )
        with session_scope(engine) as session:
            bars_repo = MarketDataRepository(session)
            for bar in bars:
                bars_repo.upsert_daily_bar(
                    instrument_id=instrument_id,
                    timestamp=bar.timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    source=bar.source,
                    adjusted=bar.adjusted.value,
                )
            sync_repo = DataSyncRunRepository(session)
            sync_run = sync_repo.get(sync_run_id)
            if sync_run is not None:
                sync_repo.mark_succeeded(
                    sync_run,
                    imported_bars=len(bars),
                    finished_at=_utcnow(),
                    duration_ms=_duration_ms(started_counter),
                )
    except Exception as exc:
        with session_scope(engine) as session:
            sync_repo = DataSyncRunRepository(session)
            sync_run = sync_repo.get(sync_run_id)
            if sync_run is not None:
                sync_repo.mark_failed(
                    sync_run,
                    error_message=_sanitize_error(exc),
                    finished_at=_utcnow(),
                    duration_ms=_duration_ms(started_counter),
                )
        raise

    return {
        "sync_run_id": sync_run_id,
        "provider": provider_name,
        "symbol": symbol,
        "imported_bars": len(bars),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }


def _normalize_bar(instrument_id: int, symbol: str, bar: Bar) -> Bar:
    return Bar(
        instrument_id=instrument_id,
        symbol=symbol,
        market=Market.A_STOCK,
        timestamp=_bar_date(bar.timestamp),
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        amount=bar.amount,
        adjusted=bar.adjusted,
        source=bar.source,
    )


def _bar_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _normalize_provider_name(provider_name: str) -> str:
    normalized = str(provider_name or "").strip().lower()
    if not normalized:
        raise ValueError("market data provider is required")
    return normalized


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip()
    if not normalized:
        raise ValueError("symbol is required")
    if len(normalized) > 32:
        raise ValueError("symbol is too long")
    return normalized


def _parse_date(value: str | date | None, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid date for {field_name}: {value}") from exc


def _derive_exchange(symbol: str) -> str:
    code = symbol.zfill(6)
    if code.startswith(("600", "601", "603", "605", "688")):
        return "SSE"
    return "SZSE"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _duration_ms(started_counter: float) -> int:
    return max(0, int((time.perf_counter() - started_counter) * 1000))


def _sanitize_error(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__)[:1000]
