# Quant Agent v3 Approval And Backtest Review Loop Design

## Goal

Build the first complete audited research loop for Quant Agent:

```text
strategy_idea agent run
  -> human candidate approval or rejection
  -> explicit MA Cross backtest job submission
  -> backtest result lookup
  -> backtest_review agent run
  -> research-only paper-trading readiness recommendation
```

V3 turns the V2 candidate payload into an operator-controlled workflow. It does not approve strategies for paper trading, create paper runs, call broker adapters, place orders, execute generated code, or let the LLM mutate executable strategy behavior.

## Current Context

Quant Agent v1 added audited `market_analysis` and `strategy_idea` agent jobs stored in `agent_runs`.

Quant Agent v2 added:

- `validate_strategy_candidate()` in `src/quant_trading/agents/candidates.py`.
- `ma_cross`-only `candidate_payload` and suggested `backtest_request_payload`.
- `requires_human_approval=true`.
- Integration into `run_strategy_idea_agent()`.
- Safety tests proving candidate generation does not create backtest, paper, broker, or backtest job rows.

The existing platform already has:

- `job_runs` for durable job lifecycle tracking.
- `backtest_runs` for backtest records.
- `POST /jobs/backtests/ma-cross` for explicit backtest job submission.
- `run_ma_cross_backtest()` as the safe deterministic backtest implementation.
- `GET /backtests` for list-style backtest read models.
- `agent_runs` for agent audit history.

V3 should connect these pieces with an auditable approval object and a new review agent.

## Non-Goals

- No generated strategy code execution.
- No arbitrary strategy templates.
- No paper trading run creation.
- No strategy approval workflow for paper trading.
- No broker adapter call or broker order event creation.
- No automatic approval of candidates.
- No automatic submission from `strategy_idea` itself.
- No LLM-driven modification of backtest request payloads.
- No front-end dashboard work in this iteration.
- No multi-user role system in this iteration.

## Scope

V3 is a complete research loop, but still a local operator workflow. It includes:

1. Candidate review persistence.
2. Approve or reject APIs.
3. Approved-candidate backtest job submission.
4. Backtest-review agent type.
5. Read APIs for candidate review records.
6. README and safety documentation.

It excludes paper trading and broker execution.

## Candidate Review Data Model

Add a new table:

```text
agent_candidate_reviews
```

Required columns:

- `id`
- `source_agent_run_id`
- `status`
- `symbol`
- `strategy_name`
- `candidate_payload`
- `backtest_request_payload`
- `operator`
- `operator_note`
- `backtest_job_run_id`
- `backtest_run_id`
- `review_agent_run_id`
- `error_message`
- `created_at`
- `updated_at`
- `decided_at`

Status values:

- `pending`
- `approved`
- `rejected`
- `backtest_submitted`
- `backtest_succeeded`
- `backtest_failed`
- `review_requested`
- `review_succeeded`
- `review_failed`

The row is created lazily when the operator approves or rejects a candidate. V3 does not need a background sync that creates pending rows for every V2 candidate.

`source_agent_run_id` must be unique. One strategy idea agent run can have at most one candidate review record.

## Candidate Approval Rules

Approval input should be intentionally narrow:

```json
{
  "operator": "local",
  "note": "approved for research backtest"
}
```

The approval service must load the source `agent_runs` row and validate:

- `agent_type == "strategy_idea"`
- `status == "succeeded"`
- `result_payload.parsed == true`
- `result_payload.validation_status == "passed"`
- `result_payload.candidate_payload` is present
- `result_payload.backtest_request_payload.job_type == "backtest_ma_cross"`
- `result_payload.requires_human_approval == true`

The operator cannot override strategy parameters during approval. Approval means "approve this exact candidate for research backtest", not "edit this candidate".

If any validation fails, return a clear failure and do not create a backtest job.

## Candidate Rejection Rules

Rejection input:

```json
{
  "operator": "local",
  "note": "insufficient thesis"
}
```

Rejection should:

- create or update a candidate review row with `status="rejected"`;
- store the source candidate payload and operator note;
- not submit a backtest job;
- not run any agent.

Rejected candidates can remain auditable but are terminal for this V3 workflow.

## Backtest Job Submission

Approval should submit a backtest job through the existing job service:

```text
submit_job_run(..., "backtest_ma_cross", backtest_request_payload["payload"], ...)
```

The service must:

- only use the payload stored in the source agent result;
- persist `backtest_job_run_id`;
- set status to `backtest_submitted`;
- not directly call `run_ma_cross_backtest()`;
- not create paper runs;
- not call broker adapters.

When the job executor is inline, the backtest job may finish before the approval API returns. The approval service should then inspect the job result payload and, if it contains a `run_id`, persist `backtest_run_id` and set status to `backtest_succeeded`.

If the job fails, set status to `backtest_failed` and persist the capped error message.

## Backtest Result Linking

Backtest run IDs may be discovered from the backtest job result:

```json
{
  "run_id": 1,
  "symbol": "000001",
  "strategy_name": "ma_cross",
  "final_equity": "100123.45",
  "equity_points": [...]
}
```

If the executor is queued and the job is not complete yet, the candidate review may remain `backtest_submitted` until a later explicit status refresh or review request.

V3 should include a small service function that refreshes a candidate review row from the linked job result. This keeps queued and inline executors compatible without introducing a scheduler.

## Backtest Review Agent

Add:

```python
AGENT_BACKTEST_REVIEW = "backtest_review"
```

Request model:

```python
BacktestReviewRequest(
    candidate_review_id: int,
    backtest_run_id: int | None = None,
)
```

The service should resolve the backtest run from the candidate review if `backtest_run_id` is omitted.

The review agent reads:

- candidate thesis/spec from the source strategy idea agent run;
- candidate payload;
- backtest request payload;
- backtest run row;
- simple result metrics available from stored backtest artifacts.

The first implementation may use conservative built-in metrics:

- `initial_cash`
- `final_equity`
- `absolute_pnl`
- `return_pct`
- `status`
- `symbol`
- `strategy_name`

If equity points or orders are easy to query, include:

- `equity_point_count`
- `max_drawdown`
- `order_count`

If not, leave them out rather than adding a broad analytics subsystem.

## Backtest Review Output

The agent result payload should include:

```json
{
  "review_status": "completed",
  "candidate_review_id": 1,
  "backtest_run_id": 1,
  "summary": "...",
  "risk_flags": ["single_symbol_only"],
  "overfit_warnings": ["no_out_of_sample_test"],
  "paper_trading_readiness": "not_ready",
  "recommended_next_steps": [
    "run an out-of-sample backtest",
    "test parameter sensitivity"
  ],
  "research_only": true
}
```

Allowed `paper_trading_readiness` values:

- `not_ready`
- `needs_review`
- `ready_for_paper_research`

The review agent must not output:

- paper trading approval;
- buy or sell instructions;
- broker/order instructions;
- profitability guarantees;
- generated strategy code.

## Backtest Review Prompt Safety

The prompt should explicitly instruct the LLM:

- do not claim future profitability;
- do not give live trading instructions;
- do not approve paper trading;
- do not call brokers or exchanges;
- do not output executable code;
- assess only research quality and risks.

If LLM output is not parseable JSON, preserve a bounded narrative and return `review_status="needs_review"`.

## API Behavior

Add candidate review APIs:

```text
GET  /agent-candidates
GET  /agent-candidates/{candidate_review_id}
POST /agent-candidates/{agent_run_id}/approve
POST /agent-candidates/{agent_run_id}/reject
POST /agent-candidates/{candidate_review_id}/refresh-backtest
```

Add review agent job API:

```text
POST /jobs/agents/backtest-review
```

The review job payload should include:

```json
{
  "candidate_review_id": 1
}
```

No new dashboard UI is required.

## Audit And Safety Invariants

- Approval creates at most one backtest job for a candidate review.
- Re-approving an already approved or submitted candidate must be rejected with a clear `409` conflict.
- Rejecting after approval must be rejected with a clear conflict.
- Backtest-review jobs must not create backtest runs, paper runs, or broker order events.
- Candidate approval must not store DeepSeek API keys in job or workflow payloads.
- Backtest-review agent runs must not store DeepSeek API keys.
- All LLM outputs remain research-only.
- Every path that creates a backtest job must preserve the operator decision record.

## Error Handling

Use clear errors:

- source agent run not found;
- source agent run is not a strategy idea;
- candidate validation did not pass;
- missing backtest request payload;
- unsupported backtest job type;
- candidate already rejected;
- candidate already submitted;
- linked backtest job has not completed;
- backtest run not found.

API mapping:

- `404` for missing agent run, candidate review, job, or backtest run.
- `409` for invalid state transitions.
- `400` for malformed approval/rejection payloads.

## Testing

Unit tests should cover:

- approval rejects non-strategy agent runs;
- approval rejects failed or unvalidated candidates;
- approval rejects unsupported backtest job types;
- approval creates a candidate review row and submits exactly one backtest job;
- duplicate approval conflicts and does not submit another backtest job;
- rejection creates a terminal rejected review row and no job;
- rejection after approval conflicts;
- refresh links completed backtest job results;
- refresh reports incomplete queued jobs clearly;
- backtest-review prompt includes safety constraints;
- backtest-review parser handles JSON and bounded narrative fallback.

Integration tests should cover:

- approve endpoint submits a `backtest_ma_cross` job from the stored V2 payload;
- approve endpoint does not create paper runs or broker order events;
- backtest-review job persists an `agent_runs` row;
- backtest-review job does not create backtest, paper, or broker rows;
- no DeepSeek API key appears in job or workflow payloads;
- list/get candidate review APIs return JSON-decoded payloads.

## Documentation

Update `README.md` under `Quant Agent`:

- explain V3 candidate approval;
- show approval and rejection curl examples;
- show backtest-review job curl example;
- state that approval submits only research backtests;
- state that review output is not paper-trading approval;
- repeat that no broker orders or paper runs are created.

## Rollout Notes

V3 needs a schema migration for `agent_candidate_reviews`.

Existing V1/V2 agent runs remain valid. Candidate review rows are created only when an operator approves or rejects an existing V2 candidate.

The first V3 implementation should support only `ma_cross`. Future strategy templates can use the same approval table if their candidate validator produces a whitelisted backtest request payload.
