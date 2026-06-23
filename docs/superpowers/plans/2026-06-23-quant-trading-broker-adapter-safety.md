# Quant Trading Broker Adapter Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a broker adapter contract, dry-run broker, and default-off trading kill-switch so future live broker integrations have a safe execution boundary.

**Architecture:** Introduce `quant_trading.execution.broker` as the adapter contract and safety guard. Keep `SimulatedBroker` as the default fill-producing adapter, add `DryRunBrokerAdapter` for would-submit diagnostics without fills, and let `PaperTradingEngine` accept an injected adapter while preserving current simulated defaults.

**Tech Stack:** Python 3.11 dataclasses/protocols, Pydantic settings, SQLAlchemy-backed paper engine, pytest, existing simulated execution components.

---

## Baseline

```bash
cd /private/tmp/quant-stage4-runtime
git status --short --branch
```

Expected: branch `codex/quant-stage4-runtime-tmp`; worktree clean after design commit.

Primary design: `docs/superpowers/specs/2026-06-23-quant-trading-broker-adapter-safety-design.md`

## File Structure

Create:

- `src/quant_trading/execution/broker.py` - broker adapter protocol, request/result dataclasses, dry-run adapter, and trading kill-switch helper.
- `tests/unit/test_broker_adapter.py` - adapter contract and dry-run coverage.

Modify:

- `src/quant_trading/config.py` - add `trading_enabled` and `broker_mode` settings.
- `src/quant_trading/execution/simulator.py` - make `SimulatedBroker` implement `submit_order()` and `cancel_order()` while preserving `execute_market_order()`.
- `src/quant_trading/execution/__init__.py` - export broker adapter types.
- `src/quant_trading/paper/engine.py` - accept injected `BrokerAdapter` and handle no-fill dry-run results.
- `tests/unit/test_settings.py` - cover new safety settings.
- `tests/unit/test_accounting.py` - cover simulated broker adapter result.
- `tests/integration/test_paper_engine.py` - cover dry-run adapter injection.
- `README.md` - document broker adapter boundary and default-off live trading.

## Task 1: Settings And Broker Contract

**Files:**

- Create: `tests/unit/test_broker_adapter.py`
- Modify: `tests/unit/test_settings.py`
- Create: `src/quant_trading/execution/broker.py`
- Modify: `src/quant_trading/config.py`
- Modify: `src/quant_trading/execution/__init__.py`

- [ ] **Step 1: Write failing broker adapter tests**

Create `tests/unit/test_broker_adapter.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from quant_trading.core.enums import Market, OrderSide, OrderStatus, OrderType
from quant_trading.core.models import Bar, OrderIntent
from quant_trading.execution.broker import (
    BrokerExecutionMode,
    DryRunBrokerAdapter,
    TradingDisabledError,
    broker_order_request_from_intent,
    ensure_trading_enabled,
)


def make_bar() -> Bar:
    return Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=date(2026, 5, 8),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=Decimal("100000"),
    )


def make_intent() -> OrderIntent:
    return OrderIntent(
        instrument_id=1,
        symbol="000001",
        side=OrderSide.BUY,
        quantity=100,
        reason="dry_run_test",
        order_type=OrderType.MARKET,
    )


def test_trading_guard_blocks_live_mode_when_disabled():
    with pytest.raises(TradingDisabledError, match="live trading is disabled"):
        ensure_trading_enabled(False, BrokerExecutionMode.LIVE)

    ensure_trading_enabled(False, BrokerExecutionMode.SIMULATED)
    ensure_trading_enabled(False, BrokerExecutionMode.DRY_RUN)


def test_dry_run_broker_records_request_without_fill():
    bar = make_bar()
    request = broker_order_request_from_intent(make_intent(), bar, "client-1")
    broker = DryRunBrokerAdapter()

    result = broker.submit_order(request, bar)

    assert result.mode is BrokerExecutionMode.DRY_RUN
    assert result.status is OrderStatus.SUBMITTED
    assert result.accepted is True
    assert result.fill is None
    assert result.broker_order_id == "dry-run-client-1"
    assert broker.submitted_requests == [request]


def test_dry_run_broker_cancel_known_and_unknown_order():
    bar = make_bar()
    request = broker_order_request_from_intent(make_intent(), bar, "client-2")
    broker = DryRunBrokerAdapter()
    submitted = broker.submit_order(request, bar)

    cancelled = broker.cancel_order(submitted.broker_order_id)
    missing = broker.cancel_order("dry-run-missing")

    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.accepted is True
    assert missing.status is OrderStatus.REJECTED
    assert missing.accepted is False
```

- [ ] **Step 2: Write failing settings tests**

Append to `tests/unit/test_settings.py`:

```python
def test_settings_default_trading_is_disabled():
    settings = AppSettings()

    assert settings.trading_enabled is False
    assert settings.broker_mode == "simulated"


def test_settings_accepts_dry_run_broker_mode_and_rejects_unknown():
    settings = AppSettings(broker_mode="dry_run")

    assert settings.broker_mode == "dry_run"

    with pytest.raises(ValueError, match="QUANT_BROKER_MODE must be simulated or dry_run"):
        AppSettings(broker_mode="live")
```

Ensure `pytest` and `AppSettings` imports already exist before adding duplicates.

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/unit/test_broker_adapter.py tests/unit/test_settings.py -q
```

Expected: FAIL because `quant_trading.execution.broker`, `trading_enabled`, and `broker_mode` do not exist.

- [ ] **Step 4: Implement broker contract**

Create `src/quant_trading/execution/broker.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from quant_trading.core.enums import OrderSide, OrderStatus, OrderType
from quant_trading.core.models import Bar, Fill, OrderIntent


class BrokerExecutionMode(StrEnum):
    SIMULATED = "simulated"
    DRY_RUN = "dry_run"
    LIVE = "live"


class TradingDisabledError(RuntimeError):
    pass


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

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True)
class BrokerOrderResult:
    broker_order_id: str
    status: OrderStatus
    mode: BrokerExecutionMode
    accepted: bool
    message: str
    fill: Fill | None = None


class BrokerAdapter(Protocol):
    mode: BrokerExecutionMode

    def submit_order(
        self,
        request: BrokerOrderRequest,
        market_bar: Bar | None = None,
    ) -> BrokerOrderResult:
        ...

    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        ...


@dataclass
class DryRunBrokerAdapter:
    submitted_requests: list[BrokerOrderRequest] = field(default_factory=list)
    mode: BrokerExecutionMode = BrokerExecutionMode.DRY_RUN

    def submit_order(
        self,
        request: BrokerOrderRequest,
        market_bar: Bar | None = None,
    ) -> BrokerOrderResult:
        self.submitted_requests.append(request)
        return BrokerOrderResult(
            broker_order_id=f"dry-run-{request.client_order_id}",
            status=OrderStatus.SUBMITTED,
            mode=self.mode,
            accepted=True,
            message="dry-run order accepted; no external order was placed",
        )

    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        known_ids = {f"dry-run-{request.client_order_id}" for request in self.submitted_requests}
        if broker_order_id in known_ids:
            return BrokerOrderResult(
                broker_order_id=broker_order_id,
                status=OrderStatus.CANCELLED,
                mode=self.mode,
                accepted=True,
                message="dry-run order cancelled",
            )
        return BrokerOrderResult(
            broker_order_id=broker_order_id,
            status=OrderStatus.REJECTED,
            mode=self.mode,
            accepted=False,
            message="dry-run order not found",
        )


def broker_order_request_from_intent(
    intent: OrderIntent,
    market_bar: Bar,
    client_order_id: str,
) -> BrokerOrderRequest:
    return BrokerOrderRequest(
        client_order_id=client_order_id,
        instrument_id=intent.instrument_id,
        symbol=intent.symbol,
        side=intent.side,
        order_type=intent.order_type,
        quantity=intent.quantity,
        limit_price=intent.limit_price,
        submitted_at=market_bar.timestamp,
        reason=intent.reason,
    )


def ensure_trading_enabled(
    trading_enabled: bool,
    adapter_mode: BrokerExecutionMode | str,
) -> None:
    mode = BrokerExecutionMode(adapter_mode)
    if mode is BrokerExecutionMode.LIVE and not trading_enabled:
        raise TradingDisabledError("live trading is disabled")
```

- [ ] **Step 5: Add settings**

Modify `src/quant_trading/config.py`:

```python
    trading_enabled: bool = Field(default=False, validation_alias="QUANT_TRADING_ENABLED")
    broker_mode: str = Field(default="simulated", validation_alias="QUANT_BROKER_MODE")
```

Add validator:

```python
    @field_validator("broker_mode", mode="before")
    @classmethod
    def normalize_broker_mode(cls, value: object) -> str:
        broker_mode = str(value or "simulated").strip().lower()
        if broker_mode not in {"simulated", "dry_run"}:
            raise ValueError("QUANT_BROKER_MODE must be simulated or dry_run")
        return broker_mode
```

In `require_api_token_for_auth()`, normalize `self.broker_mode = self.broker_mode.strip() or "simulated"`.

- [ ] **Step 6: Export execution types**

Modify `src/quant_trading/execution/__init__.py`:

```python
"""Execution package for the productized quant platform."""

from quant_trading.execution.broker import (
    BrokerAdapter,
    BrokerExecutionMode,
    BrokerOrderRequest,
    BrokerOrderResult,
    DryRunBrokerAdapter,
    TradingDisabledError,
    broker_order_request_from_intent,
    ensure_trading_enabled,
)
from quant_trading.execution.simulator import SimulatedBroker

__all__ = [
    "BrokerAdapter",
    "BrokerExecutionMode",
    "BrokerOrderRequest",
    "BrokerOrderResult",
    "DryRunBrokerAdapter",
    "SimulatedBroker",
    "TradingDisabledError",
    "broker_order_request_from_intent",
    "ensure_trading_enabled",
]
```

- [ ] **Step 7: Verify task**

Run:

```bash
python -m pytest tests/unit/test_broker_adapter.py tests/unit/test_settings.py -q
python -m py_compile src/quant_trading/execution/broker.py src/quant_trading/config.py src/quant_trading/execution/__init__.py
```

Expected: PASS.

- [ ] **Step 8: Spec and quality review**

Spec review:

- Confirm settings default to disabled/simulated.
- Confirm unknown broker mode fails validation.
- Confirm dry-run records requests without fills.
- Confirm live guard blocks live mode when disabled.

Quality review:

- Confirm no network or broker SDK dependency exists.
- Confirm dataclass validation rejects non-positive request quantity.
- Confirm exports do not create circular imports.

- [ ] **Step 9: Commit**

```bash
git add tests/unit/test_broker_adapter.py tests/unit/test_settings.py src/quant_trading/execution/broker.py src/quant_trading/config.py src/quant_trading/execution/__init__.py
git commit -m "feat: add broker adapter safety contract"
```

## Task 2: Simulated Broker Adapter And Paper Engine Injection

**Files:**

- Modify: `tests/unit/test_accounting.py`
- Modify: `tests/integration/test_paper_engine.py`
- Modify: `src/quant_trading/execution/simulator.py`
- Modify: `src/quant_trading/paper/engine.py`

- [ ] **Step 1: Write failing simulated broker adapter assertion**

Modify `tests/unit/test_accounting.py` in `test_buy_fill_reduces_cash_and_creates_position()` after `fill = broker.execute_market_order(intent, bar)`:

```python
    request = broker_order_request_from_intent(intent, bar, "unit-1")
    result = broker.submit_order(request, bar)
    assert result.accepted is True
    assert result.status == "filled"
    assert result.mode == "simulated"
    assert result.fill is not None
    assert result.fill.price == fill.price
```

Add import:

```python
from quant_trading.execution.broker import broker_order_request_from_intent
```

- [ ] **Step 2: Write failing paper engine dry-run test**

Append to `tests/integration/test_paper_engine.py`:

```python
def test_paper_tick_with_dry_run_broker_records_order_without_fill_or_position(
    legacy_sqlite_db: Path,
):
    from quant_trading.execution.broker import DryRunBrokerAdapter

    paper, engine = make_paper_engine(legacy_sqlite_db)
    dry_run_broker = DryRunBrokerAdapter()
    paper.broker = dry_run_broker
    strategy = RecordingBuyStrategy()
    account_id = paper.create_account(
        name="Dry Run Paper",
        initial_cash=Decimal("100000"),
        base_currency="CNY",
    )
    run_id = paper.start_run(
        account_id=account_id,
        symbol="000001",
        strategy=strategy,
        strategy_name=strategy.name,
        strategy_status=StrategyStatus.APPROVED,
    )

    summary = paper.run_one_tick(
        run_id=run_id,
        strategy=strategy,
        strategy_status=StrategyStatus.APPROVED,
    )

    with session_scope(engine) as session:
        order = session.scalar(select(PaperOrderORM).where(PaperOrderORM.run_id == run_id))
        fill_count = session.scalar(
            select(func.count()).select_from(PaperFillORM).where(PaperFillORM.run_id == run_id)
        )
        position_count = session.scalar(
            select(func.count())
            .select_from(PaperPositionORM)
            .where(PaperPositionORM.account_id == account_id)
        )

    assert summary.orders_created == 1
    assert summary.orders_filled == 0
    assert summary.fills_created == 0
    assert order.status == "skipped"
    assert order.risk_decision == "approved"
    assert fill_count == 0
    assert position_count == 0
    assert len(dry_run_broker.submitted_requests) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/unit/test_accounting.py tests/integration/test_paper_engine.py::test_paper_tick_with_dry_run_broker_records_order_without_fill_or_position -q
```

Expected: FAIL because `SimulatedBroker.submit_order()` and paper no-fill handling do not exist.

- [ ] **Step 4: Implement simulated broker adapter**

Modify `src/quant_trading/execution/simulator.py`:

```python
from quant_trading.core.enums import OrderStatus
from quant_trading.execution.broker import BrokerExecutionMode, BrokerOrderRequest, BrokerOrderResult
```

Inside `SimulatedBroker`:

```python
    mode = BrokerExecutionMode.SIMULATED

    def submit_order(
        self,
        request: BrokerOrderRequest,
        market_bar: Bar | None = None,
    ) -> BrokerOrderResult:
        if market_bar is None:
            raise ValueError("market_bar is required for simulated execution")
        intent = OrderIntent(
            instrument_id=request.instrument_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            reason=request.reason,
            order_type=request.order_type,
            limit_price=request.limit_price,
        )
        fill = self.execute_market_order(intent, market_bar)
        return BrokerOrderResult(
            broker_order_id=f"sim-{request.client_order_id}",
            status=OrderStatus.FILLED,
            mode=self.mode,
            accepted=True,
            message="simulated order filled",
            fill=fill,
        )

    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        return BrokerOrderResult(
            broker_order_id=broker_order_id,
            status=OrderStatus.CANCELLED,
            mode=self.mode,
            accepted=True,
            message="simulated order cancelled",
        )
```

- [ ] **Step 5: Inject adapter into paper engine**

Modify `src/quant_trading/paper/engine.py` imports:

```python
from quant_trading.execution.broker import BrokerAdapter, broker_order_request_from_intent
```

Modify constructor:

```python
        broker_adapter: BrokerAdapter | None = None,
```

Set broker:

```python
        self.broker = broker_adapter or SimulatedBroker(
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
        )
```

Replace:

```python
                fill = self.broker.execute_market_order(intent, latest)
```

with:

```python
                request = broker_order_request_from_intent(
                    intent,
                    latest,
                    client_order_id=f"paper-{run.id}-{order.id}",
                )
                broker_result = self.broker.submit_order(request, latest)
                if broker_result.fill is None:
                    repository.mark_order_skipped(order, decision.decision.value)
                    continue
                fill = broker_result.fill
```

Keep the existing `Fill(...)` reconstruction assigning `order_id=order.id`.

- [ ] **Step 6: Verify task**

Run:

```bash
python -m pytest tests/unit/test_accounting.py tests/integration/test_paper_engine.py::test_paper_tick_persists_approved_buy_and_is_idempotent tests/integration/test_paper_engine.py::test_paper_tick_with_dry_run_broker_records_order_without_fill_or_position -q
python -m py_compile src/quant_trading/execution/simulator.py src/quant_trading/paper/engine.py
```

Expected: PASS.

- [ ] **Step 7: Spec and quality review**

Spec review:

- Confirm existing simulated fills still work.
- Confirm dry-run adapter creates no fill and no position.
- Confirm paper engine can use injected adapters.

Quality review:

- Confirm backtest usage of `execute_market_order()` remains compatible.
- Confirm dry-run handling does not mutate portfolio through fake fills.
- Confirm no external broker dependency is introduced.

- [ ] **Step 8: Commit**

```bash
git add tests/unit/test_accounting.py tests/integration/test_paper_engine.py src/quant_trading/execution/simulator.py src/quant_trading/paper/engine.py
git commit -m "feat: route paper execution through broker adapter"
```

## Task 3: Documentation And Final Verification

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Update README**

Add a `Broker Adapter Safety Boundary` section before `Safety`:

```markdown
## Broker Adapter Safety Boundary

Stage 10 adds a broker adapter contract for future live integrations, but this repository still does not place real broker or exchange orders.

Safety defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `QUANT_TRADING_ENABLED` | `false` | Global kill-switch. Future live-capable adapters must refuse submission unless this is true. |
| `QUANT_BROKER_MODE` | `simulated` | Broker mode. Stage 10 supports `simulated` and `dry_run`; live mode is intentionally unavailable. |

Available adapters:

- `SimulatedBroker` creates deterministic simulated fills for backtests and paper trading.
- `DryRunBrokerAdapter` records would-submit order requests and returns accepted dry-run results without fills or external calls.

The adapter boundary is preparation for real market integration, not a broker integration itself. Real broker adapters require separate credentials handling, account synchronization, live order status reconciliation, kill-switch tests, and explicit operator approval.
```

- [ ] **Step 2: Run README grep check**

Run:

```bash
rg -n "Broker Adapter Safety Boundary|QUANT_TRADING_ENABLED|QUANT_BROKER_MODE|DryRunBrokerAdapter|does not place real broker" README.md
```

Expected: all safety claims appear.

- [ ] **Step 3: Final verification**

Run:

```bash
python -m pytest -q
python -m py_compile src/quant_trading/config.py src/quant_trading/execution/broker.py src/quant_trading/execution/simulator.py src/quant_trading/execution/__init__.py src/quant_trading/paper/engine.py
docker compose config
git diff --check
git status --short --branch
```

Expected: full suite PASS; py_compile PASS; compose config exits 0; diff check exits 0; git status shows only intended README changes before commit.

- [ ] **Step 4: Spec and quality review**

Spec review:

- Confirm README states real broker execution is unavailable.
- Confirm kill-switch and broker mode settings are documented.
- Confirm simulated and dry-run adapters are documented.

Quality review:

- Confirm docs do not imply users can trade live.
- Confirm docs name future broker work requirements.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document broker adapter safety"
```

## Plan Self-Review

- Spec coverage: settings, adapter contract, guard, dry-run, simulated adapter compatibility, paper engine injection, README, and final verification are covered.
- Placeholder scan: no TBD/TODO/fill-in placeholders are used.
- Type consistency: broker fields use `BrokerOrderRequest`, `BrokerOrderResult`, `BrokerExecutionMode`, `DryRunBrokerAdapter`, and `TradingDisabledError` consistently.

Plan complete and saved to `docs/superpowers/plans/2026-06-23-quant-trading-broker-adapter-safety.md`.

Execution recommendation: use inline execution with `superpowers:executing-plans` in this existing worktree, because this stage touches a small set of tightly coupled execution and paper-engine files.
