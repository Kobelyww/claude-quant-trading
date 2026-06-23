# Quant Trading Broker Adapter Safety Design

## Purpose

Stage 10 creates the execution boundary needed before any real broker integration. The platform currently has a `SimulatedBroker` that paper trading and backtests call directly. That is safe because it only creates simulated fills, but it also means future broker work could accidentally couple live order submission into research code without a clear contract or kill-switch.

This stage adds a broker adapter contract, dry-run execution, and a global trading kill-switch. It does not integrate any real broker, exchange, brokerage SDK, API credentials, account synchronization, or real order placement.

## Current Context

The platform already has:

- `OrderIntent`, `Fill`, `Bar`, and execution enums in `quant_trading.core`.
- `SimulatedBroker.execute_market_order(intent, bar)` for deterministic fills.
- `PaperTradingEngine` directly constructing `SimulatedBroker`.
- Backtests directly using `SimulatedBroker`.
- `AppSettings` for runtime safety options such as auth and job executor.

The current safe behavior must remain unchanged: paper trading and backtests use simulated fills only.

## Recommended Architecture

Add a small execution boundary under `quant_trading.execution`:

- `BrokerAdapter` protocol defines the minimum adapter contract for order submission and cancellation.
- `BrokerOrderRequest` describes a normalized order request derived from an `OrderIntent`.
- `BrokerOrderResult` describes the broker-side result without assuming a fill always exists.
- `BrokerExecutionMode` distinguishes `simulated`, `dry_run`, and future `live`.
- `TradingDisabledError` is raised when a live-capable adapter is used while the kill-switch is off.
- `DryRunBrokerAdapter` records what would be submitted and returns an accepted dry-run result without creating a fill.

Keep `SimulatedBroker` as the fill-producing adapter for paper trading and backtests. It can retain `execute_market_order()` for existing code while also exposing `submit_order()` through the new contract.

## Safety Model

Add runtime settings:

- `QUANT_TRADING_ENABLED=false` by default.
- `QUANT_BROKER_MODE=simulated` by default. Supported values for Stage 10: `simulated`, `dry_run`.

Rules:

1. Default runtime cannot place live orders.
2. Stage 10 has no live broker adapter implementation.
3. `DryRunBrokerAdapter` never creates fills and never calls external services.
4. Any future live-capable adapter must call a guard before submission.
5. The guard raises `TradingDisabledError` unless `trading_enabled=True`.
6. Paper trading continues to use simulated fills unless a broker adapter is explicitly injected.

The kill-switch guards the boundary where real submission would happen. It is not a substitute for risk checks, order limits, credentials separation, or account-level controls.

## API Shape

Create `src/quant_trading/execution/broker.py`.

Core types:

```python
class BrokerExecutionMode(StrEnum):
    SIMULATED = "simulated"
    DRY_RUN = "dry_run"
    LIVE = "live"


@dataclass(frozen=True)
class BrokerOrderRequest:
    client_order_id: str
    instrument_id: int
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: Decimal | None
    submitted_at: date | datetime | str
    reason: str


@dataclass(frozen=True)
class BrokerOrderResult:
    broker_order_id: str
    status: OrderStatus
    mode: BrokerExecutionMode
    accepted: bool
    message: str
    fill: Fill | None = None
```

Contract:

```python
class BrokerAdapter(Protocol):
    mode: BrokerExecutionMode

    def submit_order(self, request: BrokerOrderRequest, market_bar: Bar | None = None) -> BrokerOrderResult:
        ...

    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        ...
```

Helpers:

- `broker_order_request_from_intent(intent, market_bar, client_order_id)` builds a request.
- `ensure_trading_enabled(trading_enabled, adapter_mode)` raises for `LIVE` mode when disabled.

## Paper Trading Integration

Update `PaperTradingEngine` to accept an optional `broker_adapter`.

Default behavior:

- If `broker_adapter` is not supplied, construct `SimulatedBroker` exactly as today.
- Approved paper orders call `broker_adapter.submit_order(request, latest)`.
- If the result has no `fill`, mark the order skipped with a clear broker status message.
- If the result has a fill, persist the fill and apply accounting as today.

This allows future dry-run workflows to verify order intent routing without mutating portfolio state as a real fill.

## Error Handling

- Invalid `QUANT_BROKER_MODE` values fail settings validation.
- `BrokerOrderRequest.quantity <= 0` raises `ValueError`.
- Missing `market_bar` for `SimulatedBroker.submit_order()` raises `ValueError`.
- `DryRunBrokerAdapter.cancel_order()` returns a cancelled dry-run result for known order ids and a rejected result for unknown ids.
- `ensure_trading_enabled(False, BrokerExecutionMode.LIVE)` raises `TradingDisabledError`.

## Testing Strategy

Tests must avoid network, broker SDKs, credentials, and real order placement.

Cover:

- Settings defaults keep `trading_enabled=False` and `broker_mode="simulated"`.
- Settings accepts `dry_run` and rejects unknown broker modes.
- `ensure_trading_enabled()` blocks live mode when disabled and allows simulated/dry-run.
- `DryRunBrokerAdapter.submit_order()` records requests and returns accepted results without fills.
- `SimulatedBroker.submit_order()` returns a filled simulated result and preserves existing `execute_market_order()` behavior.
- `PaperTradingEngine` default behavior still fills approved simulated orders.
- Injecting `DryRunBrokerAdapter` into `PaperTradingEngine` creates an order but no fill, no position mutation, and a skipped order status.
- README documents that real broker execution is unavailable and guarded by `QUANT_TRADING_ENABLED`.

## Non-Goals

Stage 10 does not include:

- Real broker or exchange APIs.
- Account balance or position synchronization from a broker.
- Live order status polling.
- Webhook handling.
- Secret storage.
- Live order API endpoints.
- Market hours validation.
- Exactly-once broker order semantics.

## Success Criteria

- There is a clear broker adapter contract for future integrations.
- The default configuration cannot place real orders.
- Dry-run execution can record would-be broker submissions without creating fills.
- Paper trading remains backward compatible with simulated fills.
- Tests and README prove the safety boundary.
