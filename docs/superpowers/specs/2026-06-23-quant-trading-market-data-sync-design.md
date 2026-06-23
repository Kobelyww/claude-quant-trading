# Quant Trading Market Data Sync Design

## Purpose

Stage 6 makes market data ingestion a first-class, observable platform capability. The platform already supports legacy SQLite import, backtests, paper trading, workflow audit rows, and queued job execution. It still lacks a repeatable way to sync real market data from configured providers and inspect the sync outcome.

This stage adds daily market-data sync for A-share symbols through the existing provider abstraction and queued job runtime. It does not add live broker execution, minute bars, scheduled jobs, or websocket streaming.

## Current Context

The platform already has:

- `MarketDataProvider` protocol with `fetch_daily_bars()`.
- `AkshareProvider`, which can fetch A-share daily bars when the optional `akshare` dependency is installed.
- `InstrumentRepository.upsert_symbol()` and `MarketDataRepository.upsert_daily_bar()`.
- `job_runs` and inline/RQ job execution.
- `/jobs/...` APIs and dashboard job visibility.

The main product gap is that market data ingestion is not exposed as a durable operator workflow. Legacy import is useful for bootstrap data, but a productized trading platform needs provider-based sync with auditability, idempotent storage, and API/dashboard visibility.

## Recommended Architecture

Add a provider-driven daily market-data sync layer:

- **Provider registry** maps provider names to provider instances. Stage 6 registers `akshare` by default and allows tests to pass fake providers.
- **MarketDataSyncService** validates requests, resolves or creates an instrument, fetches bars from the provider, validates bars, upserts daily bars, and records sync lifecycle.
- **`data_sync_runs` table** records source, symbol, date range, status, imported bar count, linked `job_run_id`, error message, timing, and timestamps.
- **Job runtime integration** adds a `market_data_sync` job type. Inline mode executes immediately; RQ mode enqueues through the Stage 5 transport.
- **API and dashboard integration** expose job creation and recent sync results.

The database remains the source of truth for both stored bars and sync audit state. Providers are replaceable input adapters, not authoritative state.

## Data Model

Add `DataSyncRunORM` mapped to `data_sync_runs`.

Fields:

- `id`: integer primary key.
- `provider`: string, indexed. Stage 6 supports `akshare`.
- `symbol`: string, indexed.
- `market`: string, default `a_stock`.
- `asset_type`: string, default `stock`.
- `currency`: string, default `CNY`.
- `exchange`: string, derived from symbol when omitted.
- `start_date`: optional date.
- `end_date`: optional date.
- `status`: string, indexed. Supported values: `running`, `succeeded`, `failed`.
- `imported_bars`: integer, default `0`.
- `job_run_id`: optional integer reference to `job_runs.id`.
- `error_message`: optional text, capped at 1000 characters.
- `started_at`, `finished_at`, `created_at`: datetimes.
- `duration_ms`: optional integer.

No API tokens, provider credentials, or raw provider responses are stored in this table.

## Provider Registry

Create `quant_trading.data.providers.registry`.

Behavior:

- `build_default_provider_registry()` returns a registry containing `akshare`.
- `ProviderRegistry.get(name)` returns a provider or raises `ValueError("unknown market data provider: <name>")`.
- Provider names are normalized to lowercase.
- Tests can pass a registry with fake providers without importing or installing AkShare.

Stage 6 keeps `akshare` import lazy inside `AkshareProvider.fetch_daily_bars()`, so local tests and inline fake-provider sync do not require network access.

## Sync Service

Create `quant_trading.data.sync`.

Primary API:

```python
sync_daily_market_data(
    engine: Engine,
    provider_name: str,
    symbol: str,
    start: str | date | None,
    end: str | date | None,
    *,
    registry: ProviderRegistry | None = None,
    job_run_id: int | None = None,
) -> dict[str, Any]
```

Behavior:

1. Normalize `provider_name` and `symbol`.
2. Parse `start` and `end` as ISO dates when strings are provided.
3. Reject empty symbols and date ranges where `start_date > end_date`.
4. Derive default A-share metadata:
   - `market`: `a_stock`
   - `asset_type`: `stock`
   - `currency`: `CNY`
   - `exchange`: `SSE` for symbols starting with `600`, `601`, `603`, `605`, or `688`; otherwise `SZSE`
5. Create a `data_sync_runs` row with status `running`.
6. Upsert the instrument.
7. Fetch provider bars using the resolved instrument id and normalized date strings.
8. Validate and upsert daily bars using existing `MarketDataRepository.upsert_daily_bar()`.
9. Mark the sync run `succeeded` with imported bar count.
10. On provider or validation failure, mark the sync run `failed` with a capped error message and re-raise so the enclosing `job_run` is also marked failed.

`imported_bars` counts provider bars processed, including idempotent upserts. The storage identity remains `(instrument_id, timestamp, timeframe, adjusted, source)`.

## Job Runtime Integration

Add job type:

- `market_data_sync`

Request payload:

```json
{
  "provider": "akshare",
  "symbol": "000001",
  "start": "2026-01-01",
  "end": "2026-06-23"
}
```

Runtime dispatch calls `sync_daily_market_data()` and stores the returned payload in `job_runs.result_payload`. The returned payload includes:

- `sync_run_id`
- `provider`
- `symbol`
- `imported_bars`
- `start_date`
- `end_date`

`workflow_runs` remains the command audit trail for workflow commands. `data_sync_runs` is the market-data ingestion audit trail. `job_runs` remains the lifecycle source of truth for queued execution.

## API Design

New routes use existing token auth middleware.

- `POST /jobs/market-data/sync`
  - Body:

```json
{
  "provider": "akshare",
  "symbol": "000001",
  "start": "2026-01-01",
  "end": "2026-06-23"
}
```

  - Creates a `market_data_sync` job.

- `GET /data-sync-runs`
  - Query filters: optional `provider`, optional `symbol`, optional `status`, `limit` clamped to `1..100`.

- `GET /data-sync-runs/{sync_run_id}`
  - Returns one sync run or `404`.

Response shape:

```json
{
  "id": 1,
  "provider": "akshare",
  "symbol": "000001",
  "market": "a_stock",
  "asset_type": "stock",
  "currency": "CNY",
  "exchange": "SZSE",
  "start_date": "2026-01-01",
  "end_date": "2026-06-23",
  "status": "succeeded",
  "imported_bars": 100,
  "job_run_id": 12,
  "error_message": null,
  "started_at": "2026-06-23T10:00:00",
  "finished_at": "2026-06-23T10:00:03",
  "duration_ms": 3000,
  "created_at": "2026-06-23T10:00:00"
}
```

## Dashboard Design

Add a `Data Sync Runs` section near `Job Runs`.

Columns:

- ID
- Provider
- Symbol
- Status
- Bars
- Range
- Job
- Duration
- Error

The dashboard does not need a sync form in Stage 6. Operators can create sync jobs through the API and inspect them on the dashboard.

## Error Handling

- Unknown provider raises `ValueError` before provider calls. If the request is executed through a job, the `job_runs` row is marked failed; no `data_sync_runs` row is created because no provider-backed sync run could start.
- Empty symbols fail before provider calls.
- Invalid date format fails before provider calls.
- `start_date > end_date` fails before provider calls.
- Empty provider results are allowed and mark the sync run `succeeded` with `imported_bars=0`.
- Provider exceptions are captured in `data_sync_runs.error_message`, capped at 1000 characters, and re-raised for job failure.
- API token values are never stored.

## Testing Strategy

Tests should avoid real network calls.

Cover:

- Provider registry normalization and unknown-provider errors.
- Sync service success with a fake provider and idempotent upserts.
- Sync service validation failures before provider calls.
- Sync service provider failure marks sync run failed.
- Alembic migration creates `data_sync_runs`.
- Job runtime executes `market_data_sync` and links `job_run_id`.
- `POST /jobs/market-data/sync`, `GET /data-sync-runs`, and `GET /data-sync-runs/{id}`.
- Auth coverage for new read and job routes.
- Dashboard rendering of recent data sync runs.
- Existing full test suite still passes.

## Non-Goals

This stage does not include:

- Live broker or exchange order execution.
- Minute bars or tick data.
- Scheduled recurring sync.
- Provider fallback or routing by market.
- Credential storage.
- Streaming market data.
- Multi-user data entitlements.

## Acceptance Criteria

- Operators can create a market-data sync job through `/jobs/market-data/sync`.
- The sync path can use fake providers in tests and `akshare` in real local runs.
- Synced bars are persisted idempotently through existing market bar storage.
- Operators can list and inspect sync outcomes through API.
- Dashboard shows recent data sync runs with status, counts, linked job, and errors.
- `data_sync_runs` records ingestion audit state.
- `job_runs` remains the queued execution lifecycle source of truth.
- Full tests and Docker Compose config pass.
