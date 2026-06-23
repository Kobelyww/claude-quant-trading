# Quant Trading Broker Order Audit Design

## Purpose

Stage 11 adds a durable audit trail for broker adapter submissions. Stage 10 introduced `BrokerAdapter`, `SimulatedBrokerAdapter`, `DryRunBrokerAdapter`, and a default-off trading kill-switch, but broker adapter submissions are only visible through in-memory adapter state or downstream paper fills. A real-market-ready platform needs persistent evidence for every order request sent to an execution boundary.

This stage records broker order request and result metadata whenever paper trading submits an approved order to a broker adapter. It does not add live broker integration, broker credentials, order status polling, webhooks, or a public order-submission API.

## Current Context

The platform already has:

- `PaperOrderORM` for paper order intent state.
- `PaperFillORM` for simulated fills.
- `RiskDecisionORM` for risk decisions.
- `BrokerOrderRequest` and `BrokerOrderResult` in `quant_trading.execution.broker`.
- `PaperTradingEngine` routing approved paper orders through `broker.submit_order()`.
- Alembic migrations and repository patterns for durable operational tables.

The gap is that a dry-run broker submission can be accepted without creating a fill, and a simulated broker submission can create a fill without a normalized record of the adapter request/result pair. Future live adapters need that record before they exist.

## Recommended Architecture

Add a new table, ORM, and repository for broker order events.

Table: `broker_order_events`

Fields:

- `id`: integer primary key.
- `run_id`: optional reference to `paper_runs.id`, indexed.
- `order_id`: optional reference to `paper_orders.id`, indexed.
- `broker_mode`: string, indexed. Values come from `BrokerExecutionMode`.
- `client_order_id`: string, indexed.
- `broker_order_id`: optional string, indexed.
- `status`: string, indexed. Values come from `OrderStatus`.
- `accepted`: boolean, indexed.
- `request_payload`: JSON text with normalized request metadata.
- `result_payload`: JSON text with normalized result metadata.
- `message`: short broker adapter message, capped.
- `created_at`: datetime, indexed.

Keep the audit event append-only. Stage 11 does not update existing audit rows.

## Payload Policy

Persist normalized, non-secret metadata only.

`request_payload` includes:

- `client_order_id`
- `instrument_id`
- `symbol`
- `side`
- `order_type`
- `quantity`
- `limit_price`
- `submitted_at`
- `reason`

`result_payload` includes:

- `broker_order_id`
- `status`
- `mode`
- `accepted`
- `message`
- `has_fill`
- optional fill summary: `instrument_id`, `symbol`, `side`, `quantity`, `price`, `commission`, `slippage`, `filled_at`

Do not persist API tokens, broker credentials, raw provider payloads, full exception tracebacks, account secrets, or unbounded broker responses.

## Paper Trading Integration

After risk approval and before fill accounting:

1. Build a `BrokerOrderRequest`.
2. Call `broker.submit_order(request, latest_bar)`.
3. Record a `broker_order_events` row with the request/result pair.
4. If `result.fill is None`, mark the paper order skipped and continue.
5. If `result.fill` exists, continue existing fill persistence and accounting.

The audit event should be written in the same database session as the paper tick. If the tick transaction rolls back, the audit event rolls back too, keeping paper state internally consistent.

## API And Dashboard Impact

Stage 11 does not add public API endpoints or dashboard tables. The repository gives internal code and tests a query path. A later stage can expose broker order audit history in the operator dashboard.

## Error Handling

- Invalid or non-dict payload values are rejected at repository boundaries.
- Broker result messages are capped to 512 characters.
- Missing `run_id` or `order_id` is allowed at the schema level for future non-paper order sources, but paper engine always supplies both.
- Audit write failure should fail the paper tick transaction. Silent missing broker audit is worse than surfacing an operational error.

## Testing Strategy

Tests must not use network, broker SDKs, credentials, or real order placement.

Cover:

- Alembic migration creates `broker_order_events`.
- ORM `create_all()` includes the table.
- Repository records and lists broker order events.
- Simulated paper tick records a broker event with `mode=simulated`, `status=filled`, `accepted=true`, and `has_fill=true`.
- Dry-run paper tick records a broker event with `mode=dry_run`, `status=submitted`, `accepted=true`, and `has_fill=false`.
- Dry-run still creates no fill and no position.
- README documents broker order audit as part of the safety boundary.
- Existing broker adapter, paper engine, migration, and full test suite still pass.

## Non-Goals

Stage 11 does not include:

- Live broker execution.
- Broker credential storage.
- External order status reconciliation.
- Dashboard or API endpoints for broker audit.
- Retry/outbox semantics.
- Exactly-once live order submission guarantees.

## Success Criteria

- Every paper engine broker adapter submission has a durable audit row.
- Simulated and dry-run broker modes are both auditable.
- Audit payloads are normalized and do not include credentials or unbounded raw responses.
- Existing paper trading behavior remains backward compatible.
- Full tests and migration checks pass.
