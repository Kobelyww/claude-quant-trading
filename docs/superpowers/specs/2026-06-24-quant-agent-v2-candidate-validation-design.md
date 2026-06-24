# Quant Agent v2 Candidate Validation Design

## Goal

Upgrade the strategy idea agent from a structured-text assistant into a research-candidate generator that can validate LLM output, map safe ideas to a whitelisted strategy template, and produce a human-approved backtest request.

Quant Agent v2 remains research-only. It does not execute generated code, submit backtest jobs automatically, create paper runs, approve strategies, call broker adapters, or place orders.

## Current Context

Quant Agent v1 added:

- `strategy_idea` and `market_analysis` agent types.
- `agent_runs` audit rows.
- DeepSeek and fake LLM client boundary.
- Agent job APIs under `/jobs/agents/...`.
- Agent read APIs under `/agent-runs`.
- Safety tests proving agent jobs do not create broker order events.

The existing trading runtime already has a safe, deterministic moving-average crossover path:

- `MACrossStrategy` in `src/quant_trading/strategy/builtin/ma_cross.py`.
- `run_ma_cross_backtest()` in `src/quant_trading/workflows/operations.py`.
- `BACKTEST_MA_CROSS = "backtest_ma_cross"` in `src/quant_trading/jobs/runtime.py`.
- `POST /jobs/backtests/ma-cross` in `src/quant_trading/api/routes/jobs.py`.

V2 should connect the strategy idea agent to that existing safe backtest shape without letting the LLM define executable behavior.

## Non-Goals

- No execution of LLM-generated Python, SQL, shell, or expressions.
- No dynamic strategy class creation.
- No automatic `submit_job_run()` call for backtests.
- No paper trading run creation.
- No strategy approval workflow.
- No broker adapter call or broker order event creation.
- No support for arbitrary strategy templates.
- No front-end dashboard work in this iteration.

## User-Facing Capability

The strategy idea agent should still accept the v1 input:

- `idea`, required and capped at `4000` characters.
- optional `symbol`, capped at `32` characters.
- optional `market_context`, capped at `2000` characters.
- optional `constraints`.

When the LLM returns a supported structured idea, the service should add validation and candidate fields to the existing result payload:

```json
{
  "validation_status": "passed",
  "validation_errors": [],
  "safety_flags": [],
  "candidate_payload": {
    "strategy_name": "ma_cross",
    "symbol": "000001",
    "parameters": {
      "short_window": 5,
      "long_window": 20,
      "order_size": 100
    },
    "requires_human_approval": true
  },
  "backtest_request_payload": {
    "job_type": "backtest_ma_cross",
    "payload": {
      "symbol": "000001",
      "short_window": 5,
      "long_window": 20,
      "order_size": 100,
      "initial_cash": "100000"
    }
  },
  "requires_human_approval": true
}
```

When output is parseable but incomplete or unsafe, the agent run should still succeed as an audited research result, but return:

```json
{
  "validation_status": "failed",
  "validation_errors": ["missing field: exit_rules"],
  "safety_flags": ["contains_executable_code"],
  "candidate_payload": null,
  "backtest_request_payload": null,
  "requires_human_approval": true
}
```

If LLM parsing fails entirely, keep v1 behavior with `parsed=false`, bounded `narrative`, and include `validation_status="needs_review"`.

## Supported Strategy Template

V2 supports only one template:

```text
ma_cross
```

The validator should accept either:

- an explicit `strategy_template` value of `ma_cross`, or
- enough structured evidence to safely infer an MA cross idea from entry/exit rules and parameters.

Inference should be conservative:

- If the LLM provides an explicit unsupported template, return `validation_status="failed"`.
- If no explicit template is present and the rules/parameters are not enough to infer `ma_cross`, return `validation_status="needs_review"`.
- `needs_review` must not include a candidate or backtest request.

## Required Strategy Spec Fields

For a parsed JSON object to be a complete strategy spec, it must include:

- `thesis`
- `market_regime_assumption`
- `entry_rules`
- `exit_rules`
- `risk_controls`
- `parameters_to_test`
- `data_requirements`
- `failure_modes`
- `backtest_readiness`

Missing fields should be reported in `validation_errors`.

## Candidate Parameter Rules

The MA cross candidate should be built from explicit LLM parameters when safe. Supported parameter keys:

- `short_window`
- `long_window`
- `order_size`
- `initial_cash`

If a supported parameter is missing, use safe defaults:

- `short_window=5`
- `long_window=20`
- `order_size=100`
- `initial_cash="100000"`

Validation rules:

- `short_window` must be an integer greater than `0`.
- `long_window` must be an integer greater than `short_window`.
- `order_size` must be an integer greater than `0`.
- `initial_cash` must be a finite decimal string greater than `0`.
- `symbol` must come from the request or the LLM output and must be non-empty to create a backtest request.

If any rule fails, return `validation_status="failed"` with no candidate.

## Safety Detection

The validator should flag and reject parsed specs containing:

- Python code fences or obvious executable syntax such as `def `, `class `, `import `, `exec(`, `eval(`, or `subprocess`.
- Broker/order execution wording such as broker API calls, exchange submission, live order placement, or direct buy/sell instructions.
- Profitability guarantees or guaranteed return language.

Safety flags should be machine-readable strings such as:

- `contains_executable_code`
- `contains_broker_or_order_instruction`
- `contains_profitability_claim`
- `contains_live_trading_recommendation`

Any safety flag should prevent candidate generation.

## Architecture

Create a focused candidate validation module:

```text
src/quant_trading/agents/candidates.py
```

This module owns:

- strategy spec field validation
- safety scanning
- MA cross candidate construction
- backtest request payload construction

It should not import broker adapters, paper trading code, job submission services, or arbitrary strategy classes. It may import the `BACKTEST_MA_CROSS` constant only if doing so does not introduce circular imports; otherwise use the stable string `"backtest_ma_cross"`.

Expected public function:

```python
def validate_strategy_candidate(
    parsed_payload: dict,
    *,
    request_symbol: str | None,
) -> dict:
    ...
```

The return dict should contain:

- `validation_status`
- `validation_errors`
- `safety_flags`
- `candidate_payload`
- `backtest_request_payload`
- `requires_human_approval`

## Service Integration

`run_strategy_idea_agent()` should call `validate_strategy_candidate()` only when `parse_strategy_idea_response()` returns `parsed=true`.

Result behavior:

- `parsed=false`: set `validation_status="needs_review"` and no candidate.
- `parsed=true`, validation passed: include candidate and backtest request payload.
- `parsed=true`, validation failed: include errors/flags and no candidate.

All additions stay inside `result_payload`; no schema migration is needed.

## API Behavior

No new endpoints are required in this iteration.

Existing endpoint:

```text
POST /jobs/agents/strategy-idea
```

returns the same job shape, with the enriched `result_payload` inside the job result.

Existing read endpoint:

```text
GET /agent-runs/{agent_run_id}
```

returns the persisted enriched `result_payload`.

## Audit And Safety Invariants

- `agent_runs.result_payload` stores candidate metadata and suggested backtest request only.
- `job_runs` and `workflow_runs` must not store DeepSeek API keys.
- Candidate generation must not create rows in:
  - `backtest_runs`
  - `paper_runs`
  - `broker_order_events`
- The candidate must always include `requires_human_approval=true`.

## Testing

Unit tests should cover:

- valid `ma_cross` spec creates candidate and backtest request.
- missing required fields returns `validation_status="failed"`.
- unknown template returns `validation_status="failed"`.
- code-like content sets `contains_executable_code` and blocks candidate.
- broker/order instruction sets `contains_broker_or_order_instruction` and blocks candidate.
- invalid parameters block candidate.
- unparseable LLM text keeps `parsed=false` and `validation_status="needs_review"`.

Integration tests should cover:

- `run_strategy_idea_agent()` persists a passed candidate.
- strategy idea job API returns the candidate in `result_payload`.
- candidate generation does not create `backtest_runs`, `paper_runs`, or `broker_order_events`.
- missing DeepSeek credentials still persist a failed `agent_run`.

## Documentation

Update `README.md` under `Quant Agent v1` or rename that section to `Quant Agent` and document:

- Strategy idea jobs now validate candidate specs.
- Only `ma_cross` is supported in v2.
- Backtest request payloads are suggestions only.
- Operators must submit backtests explicitly.
- Agent outputs remain research-only.
