# Quant Trading Pre-Live Safety And Operations Design

## Purpose

This milestone moves Quant Trading from a research and paper-trading workbench toward a
pre-live operating model without adding real broker execution.

The platform now has a safe broker adapter boundary, broker order audit records, an
operator-gated Quant Agent research loop, and deterministic research validation reports.
The next product gap is the layer that decides whether an order intent is operationally
eligible to reach an execution boundary at all.

This design adds a pre-live safety and operations layer:

- A durable order-intent state machine before broker adapter submission.
- Risk limit profiles that can be evaluated independently of paper-trading internals.
- Operator approval requests for high-impact or policy-sensitive order intents.
- Global kill-switch controls with reasoned audit events.
- Operations readiness summaries for jobs, stale data, stuck workflows, and execution
  safety posture.

It remains research and paper-only. It does not place real broker or exchange orders.

## Current Context

Verified on 2026-06-26 in branch `codex/quant-agent-v3-approval-review-loop`.

The platform already has:

- `BrokerAdapter`, `SimulatedBrokerAdapter`, `DryRunBrokerAdapter`,
  `BrokerOrderRequest`, `BrokerOrderResult`, and `ensure_trading_enabled()` in
  `src/quant_trading/execution/broker.py`.
- `PaperTradingEngine` routing approved paper orders through a broker adapter and
  recording `broker_order_events`.
- A reusable `RiskEngine` with strategy approval, data presence, price sanity, max
  order value, and max gross exposure rules.
- Agent candidate approval, data quality reports, research validation reports, and a
  capped backtest review recommendation.
- Job runs, workflow audit rows, scheduled data syncs, job event streams, and a
  dashboard-oriented operations workbench.
- Runtime safety defaults:
  - `QUANT_TRADING_ENABLED=false`
  - `QUANT_BROKER_MODE=simulated`
  - supported broker modes are `simulated` and `dry_run`

The remaining gap is that paper trading still evaluates risk inline and then submits
directly to the broker adapter. That is acceptable for local simulated paper trading, but
it is not a productized pre-live boundary. Before any future live-capable adapter exists,
the system needs a separate operational control plane that can block, approve, explain,
and audit order intents before they reach execution.

## Approaches Considered

### A. Operations-only hardening

Add dashboards, alerts, retries, and runbooks around the existing paper engine.

This is low risk and useful, but it leaves the execution boundary weak. Operators could
see failures after the fact, yet there would still be no durable order-intent state
machine, no approval queue, and no policy layer between agent research and execution.

### B. OMS and risk-first pre-live safety layer

Add a small order management and safety service in front of broker adapter submission.
Every execution-bound intent becomes a durable order intent, passes a policy profile,
checks kill-switch state, may require manual approval, and only then becomes eligible
for simulated or dry-run broker submission.

This is the recommended approach because it improves the exact boundary that must be
correct before future broker work. It also keeps the implementation incremental: no real
broker SDK, no credentials, and no live execution are needed.

### C. Data and research gate expansion

Continue strengthening data quality, walk-forward validation, and benchmark evaluation.

This remains important, but the current milestone already added a research validation
layer. The next risk is not more research scoring; it is preventing any future execution
path from bypassing operational controls.

## Chosen Architecture

Implement approach B.

Create a pre-live safety layer under a new `quant_trading.operations` package, with
clear boundaries from existing research, paper, and broker modules:

```text
agent research / paper strategy
  -> order intent proposal
  -> pre-live order intent state machine
  -> safety policy evaluation
  -> optional operator approval
  -> broker adapter submission eligibility
  -> simulated or dry-run broker adapter
  -> broker_order_events audit
```

The layer should be usable by paper trading first, but it should not be paper-specific.
Its data model must allow future non-paper order sources while keeping the default
runtime unable to submit live orders.

## Non-Goals

This milestone does not include:

- Real broker or exchange APIs.
- Live order placement.
- Broker credentials or secret storage.
- Account balance or position synchronization from a broker.
- Live order status polling.
- Webhook handling.
- Public APIs that submit live orders.
- Execution of LLM-generated strategy code.
- Automatic promotion from research validation to paper trading or live trading.
- Multi-user role-based access control beyond operator names and audit notes.
- Exchange holiday calendars or market microstructure simulation.
- Exactly-once live order submission guarantees.

## Data Model

Add durable operational tables through Alembic and SQLAlchemy models.

### `execution_safety_states`

Stores global safety posture.

Fields:

- `id`: integer primary key.
- `scope`: string, indexed. Initial value: `global`.
- `kill_switch_active`: boolean, indexed. Default: `false`.
- `dry_run_enabled`: boolean, indexed. Default: `true`.
- `simulated_enabled`: boolean, indexed. Default: `true`.
- `live_enabled`: boolean, indexed. Default: `false`.
- `reason`: text, capped to 1024 characters.
- `updated_by`: string, capped to 128 characters.
- `updated_at`: datetime, indexed.

Initial seed:

- `scope="global"`
- `kill_switch_active=false`
- `dry_run_enabled=true`
- `simulated_enabled=true`
- `live_enabled=false`
- `reason="default simulated and dry-run startup"`
- `updated_by="system"`

The kill switch defaults to inactive so the existing simulated paper-trading loop remains
usable. An active kill switch blocks simulated and dry-run broker submission eligibility.
Live remains disabled because the runtime has no live broker mode in this milestone.

### `execution_order_intents`

Stores execution-bound order intents before adapter submission.

Fields:

- `id`: integer primary key.
- `source_type`: string, indexed. Initial values: `paper_run`, `manual_test`.
- `source_id`: nullable integer, indexed.
- `paper_run_id`: nullable foreign key to `paper_runs.id`, indexed.
- `paper_order_id`: nullable foreign key to `paper_orders.id`, indexed.
- `client_order_id`: string, unique, indexed.
- `symbol`: string, indexed.
- `instrument_id`: integer, indexed.
- `side`: string.
- `order_type`: string.
- `quantity`: integer.
- `limit_price`: nullable decimal stored as string-compatible numeric.
- `estimated_price`: nullable decimal stored as string-compatible numeric.
- `estimated_notional`: decimal stored as string-compatible numeric.
- `broker_mode`: string, indexed. Allowed values: `simulated`, `dry_run`.
- `status`: string, indexed.
- `risk_profile_name`: string, indexed.
- `risk_summary_payload`: JSON text.
- `approval_required`: boolean, indexed.
- `approval_request_id`: nullable foreign key to `operator_approval_requests.id`.
- `blocked_reason_code`: nullable string, indexed.
- `blocked_reason`: nullable text, capped to 1024 characters.
- `created_at`: datetime, indexed.
- `updated_at`: datetime, indexed.
- `submitted_at`: nullable datetime, indexed.

Allowed status values:

- `created`
- `risk_approved`
- `approval_required`
- `operator_approved`
- `blocked`
- `submitted`
- `skipped`
- `cancelled`

State transitions:

```text
created -> risk_approved
created -> approval_required
created -> blocked
approval_required -> operator_approved
approval_required -> blocked
risk_approved -> submitted
operator_approved -> submitted
risk_approved -> skipped
operator_approved -> skipped
created -> cancelled
approval_required -> cancelled
risk_approved -> cancelled
```

Invalid transitions raise a domain error and record no partial state.

### `execution_order_decisions`

Stores each safety decision made for an order intent.

Fields:

- `id`: integer primary key.
- `order_intent_id`: foreign key to `execution_order_intents.id`, indexed.
- `decision_type`: string, indexed. Allowed values: `approved`, `approval_required`,
  `blocked`, `skipped`.
- `reason_code`: string, indexed.
- `message`: text, capped to 1024 characters.
- `policy_payload`: JSON text.
- `created_at`: datetime, indexed.

Decision rows are append-only.

### `operator_approval_requests`

Stores manual approval gates.

Fields:

- `id`: integer primary key.
- `resource_type`: string, indexed. Initial value: `execution_order_intent`.
- `resource_id`: integer, indexed.
- `status`: string, indexed. Allowed values: `pending`, `approved`, `rejected`,
  `expired`, `cancelled`.
- `reason_code`: string, indexed.
- `requested_by`: string, capped to 128 characters.
- `requested_at`: datetime, indexed.
- `decided_by`: nullable string, capped to 128 characters.
- `decided_at`: nullable datetime, indexed.
- `operator_note`: text, capped to 2048 characters.
- `expires_at`: nullable datetime, indexed.

One order intent can have at most one active approval request.

### `safety_incidents`

Stores operational safety incidents that operators need to see.

Fields:

- `id`: integer primary key.
- `severity`: string, indexed. Allowed values: `info`, `warning`, `critical`.
- `category`: string, indexed. Initial values: `kill_switch`, `stale_data`,
  `stuck_job`, `policy_block`, `broker_boundary`, `system`.
- `status`: string, indexed. Allowed values: `open`, `acknowledged`, `resolved`.
- `resource_type`: nullable string, indexed.
- `resource_id`: nullable integer, indexed.
- `reason_code`: string, indexed.
- `message`: text, capped to 2048 characters.
- `payload`: JSON text.
- `created_at`: datetime, indexed.
- `acknowledged_by`: nullable string, capped to 128 characters.
- `acknowledged_at`: nullable datetime.
- `resolved_by`: nullable string, capped to 128 characters.
- `resolved_at`: nullable datetime.

### `kill_switch_events`

Stores every safety-state change.

Fields:

- `id`: integer primary key.
- `scope`: string, indexed.
- `previous_state_payload`: JSON text.
- `new_state_payload`: JSON text.
- `operator`: string, capped to 128 characters.
- `reason`: text, capped to 1024 characters.
- `created_at`: datetime, indexed.

Events are append-only.

## Risk Profiles

Add a policy profile object under `quant_trading.operations.safety`.

Initial profile: `pre_live_default`.

Fields:

- `name`: `pre_live_default`
- `max_single_order_notional`: default `100000`
- `max_gross_exposure_ratio`: default `1.0`
- `max_daily_turnover`: default `300000`
- `max_daily_order_count`: default `20`
- `max_drawdown_stop_ratio`: default `0.10`
- `stale_data_max_age_days`: default `10`
- `manual_approval_notional`: default `50000`
- `manual_approval_sell_without_position`: default `true`
- `allowed_broker_modes`: `["simulated", "dry_run"]`

The profile can be constructed from code defaults and optionally overridden by a
validated JSON payload in application settings or a future database row. This milestone
should not add a broad policy-editor UI.

## Safety Service

Create `PreLiveSafetyService`.

Required responsibilities:

1. Accept an `OrderIntent`, current market bar, portfolio snapshot, broker mode, source
   metadata, and risk profile name.
2. Create or reuse an idempotent `execution_order_intents` row by `client_order_id`.
3. Evaluate global safety state.
4. Evaluate the risk profile.
5. Create append-only `execution_order_decisions`.
6. Create `operator_approval_requests` when policy requires human approval.
7. Return a typed decision object that tells callers whether broker submission is
   allowed, blocked, skipped, or waiting for approval.

Public API shape:

```python
@dataclass(frozen=True)
class PreLiveSafetyDecision:
    order_intent_id: int
    decision_type: str
    reason_code: str
    message: str
    broker_submission_allowed: bool
    approval_request_id: int | None = None


class PreLiveSafetyService:
    def evaluate_order_intent(...) -> PreLiveSafetyDecision:
        ...

    def approve_order_intent(
        self,
        order_intent_id: int,
        *,
        operator: str,
        note: str,
    ) -> PreLiveSafetyDecision:
        ...

    def reject_order_intent(
        self,
        order_intent_id: int,
        *,
        operator: str,
        note: str,
    ) -> PreLiveSafetyDecision:
        ...
```

Decision reason codes must be machine-readable. Initial reason codes:

- `approved`
- `manual_approval_required_notional`
- `manual_approval_required_sell_without_position`
- `blocked_global_kill_switch`
- `blocked_live_mode_unavailable`
- `blocked_broker_mode_disabled`
- `blocked_stale_market_data`
- `blocked_invalid_price`
- `blocked_max_single_order_notional`
- `blocked_max_gross_exposure`
- `blocked_max_daily_turnover`
- `blocked_max_daily_order_count`
- `blocked_drawdown_stop`
- `blocked_invalid_state_transition`
- `skipped_duplicate_client_order_id`

## Paper Trading Integration

Integrate the safety service into `PaperTradingEngine` after existing strategy and risk
checks but before broker adapter submission.

Default behavior must remain safe and backward compatible:

1. Strategy creates an intent.
2. Existing `RiskEngine` evaluates the intent.
3. If rejected, current paper-order rejection behavior remains unchanged.
4. If approved, `PreLiveSafetyService.evaluate_order_intent()` records and evaluates the
   execution-bound intent.
5. If safety blocks the intent, the paper order is marked skipped with the safety reason
   code. No broker adapter call happens.
6. If safety requires operator approval, the paper order is marked skipped or pending
   according to the existing paper-order state vocabulary. No broker adapter call happens.
7. If safety allows submission, broker adapter submission proceeds as today and
   `broker_order_events` is recorded as today.

For this milestone, pending operator approval does not asynchronously resume the same
paper tick. Approval makes the order intent eligible for a later explicit operator
command or future engine path. This avoids hidden background submission.

## Operator APIs

Add protected API endpoints. They use the existing authentication middleware and require
the same token protection as other workflow commands when `QUANT_REQUIRE_AUTH=true`.

Read endpoints:

```text
GET /ops/readiness
GET /ops/safety-state
GET /ops/order-intents
GET /ops/order-intents/{order_intent_id}
GET /ops/approval-requests
GET /ops/incidents
GET /ops/kill-switch-events
```

Command endpoints:

```text
POST /ops/kill-switch/enable
POST /ops/kill-switch/disable
POST /ops/order-intents/{order_intent_id}/approve
POST /ops/order-intents/{order_intent_id}/reject
POST /ops/incidents/{incident_id}/acknowledge
POST /ops/incidents/{incident_id}/resolve
```

Payloads require:

- `operator`: non-empty string, max 128 characters.
- `note` or `reason`: non-empty string, max 2048 characters for approvals and incidents,
  max 1024 characters for kill-switch events.

The endpoints must not submit live orders. Approval only updates safety state for an
order intent. A separate explicit command is required before any future broker adapter
submission path can use that approval.

## Operations Readiness

`GET /ops/readiness` returns a compact status object for dashboard and monitoring use.

Fields:

- `environment`: from `QUANT_APP_ENV`.
- `trading_enabled`: from settings.
- `broker_mode`: from settings.
- `global_kill_switch_active`: from `execution_safety_states`.
- `live_execution_available`: always `false` in this milestone.
- `open_critical_incidents`: integer.
- `open_warning_incidents`: integer.
- `pending_approval_requests`: integer.
- `stuck_jobs`: integer.
- `failed_jobs_24h`: integer.
- `stale_data_reports`: integer.
- `latest_data_sync_status`: nullable status summary.
- `latest_research_validation_status`: nullable status summary.
- `safe_for_simulated_paper`: boolean.
- `safe_for_dry_run`: boolean.
- `safe_for_live`: always `false`.
- `reasons`: list of machine-readable reason codes.

Readiness is informational. It is not an execution approval.

## Dashboard Impact

Add one dashboard section named `Operations Safety`.

It should show:

- Current kill-switch state.
- Current broker mode and trading-enabled setting.
- Readiness booleans for simulated paper, dry-run, and live.
- Pending approval count.
- Open incident count by severity.
- Recent order-intent decisions.
- Recent kill-switch events.

The dashboard can use existing server-rendered patterns. It does not need a complex
front-end framework in this milestone.

## Safety Invariants

These invariants must hold after implementation:

1. Default runtime cannot submit live orders.
2. Default local simulated paper trading remains runnable when other policy checks pass.
3. No code path in this milestone can instantiate or call a real broker SDK.
4. `dry_run` never creates fills or positions.
5. Agent outputs cannot directly create execution orders.
6. Research validation readiness is a cap, not approval to trade.
7. Operator approval of a candidate is not operator approval of an execution order.
8. Operator approval of an execution order does not submit the order by itself.
9. Kill-switch state is checked before broker adapter submission eligibility.
10. Every blocked decision has a machine-readable reason code.
11. Safety decisions and kill-switch changes are durable and auditable.
12. Secrets, tokens, raw credentials, and unbounded exception payloads are never persisted.
13. Live readiness remains `false` until a separate live-broker design and implementation
    explicitly changes the supported broker modes.

## Error Handling

- Invalid broker mode requests return `400` from APIs and raise a domain error in services.
- Unknown order-intent IDs return `404`.
- Invalid state transitions return `409` and create no new state transition.
- Duplicate `client_order_id` values are idempotent when the payload matches the existing
  order intent and rejected when the payload conflicts.
- Approval requests that are no longer pending return `409`.
- Kill-switch changes require an operator and reason; missing values return `422`.
- Safety service failures must prevent broker adapter submission.
- Incident and decision messages are capped before persistence.

## Testing Strategy

Tests must not use network, broker SDKs, credentials, or real order placement.

Unit tests:

- Risk profile default values and validation.
- Global safety state blocks simulated and dry-run broker submission while kill switch is active.
- Simulated and dry-run mode eligibility when kill switch is disabled and profile checks pass.
- Live mode is always blocked in this milestone.
- Notional, exposure, daily turnover, daily count, stale data, invalid price, and drawdown
  stops produce expected reason codes.
- Manual approval is required above the notional approval threshold.
- Manual approval is required for sell orders without an existing position.
- State machine rejects invalid transitions.
- Duplicate `client_order_id` handling is idempotent only for matching payloads.

Integration tests:

- Alembic migration creates all new tables and indexes.
- `create_all()` includes all new ORM tables.
- Paper tick records an `execution_order_intents` row before broker adapter submission.
- Safety-blocked paper tick creates no `broker_order_events`, no fills, and no position
  mutation.
- Approval-required paper tick creates an approval request and no broker submission.
- Safety-approved simulated paper tick preserves current fill/accounting behavior and
  records both safety decision and broker audit rows.
- Dry-run paper tick records safety decision and broker audit rows but creates no fills
  or positions.
- Kill-switch API writes `kill_switch_events` and changes readiness output.
- Readiness endpoint reports pending approvals, open incidents, stuck jobs, and live
  readiness `false`.
- Dashboard renders the operations safety section.
- Full test suite passes.

Spec and quality reviews:

- Review implementation against this spec after every task.
- Run a quality review for naming, boundaries, edge cases, persistence behavior, and test
  coverage after every task.

## Implementation Sequence

1. Add migrations, ORM models, repositories, and seeded default safety state.
2. Add risk profile and safety service with unit tests.
3. Integrate safety service into paper trading with integration tests.
4. Add operator APIs for safety state, order intents, approvals, incidents, and readiness.
5. Add dashboard operations safety section.
6. Update README with safety workflow, endpoints, and non-live constraints.
7. Run spec compliance review, quality review, migration checks, and the full test suite.

## Success Criteria

- Every broker-submission-eligible paper order has a durable pre-live order-intent record.
- Blocked or approval-required intents never call a broker adapter.
- Operator approvals are explicit, audited, and separate from research candidate approval.
- Kill-switch changes are explicit, audited, and visible through readiness output.
- Operations readiness exposes the current safety posture without implying live readiness.
- The project remains unable to place real broker or exchange orders.
- Tests prove simulated and dry-run behavior remains safe and backward compatible.
