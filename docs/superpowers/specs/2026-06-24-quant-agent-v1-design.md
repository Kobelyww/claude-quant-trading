# Quant Agent v1 Design

## Goal

Add a productized research-agent layer to the quant trading platform. The first version turns the legacy AI strategy and market-analysis ideas into audited, job-driven services on the current `main` runtime.

Quant Agent v1 is intentionally research-only. It helps operators analyze market data and structure strategy ideas, but it does not place orders, execute generated code, approve strategies, or start paper trading runs.

## Current Context

The `main` branch already includes the productized runtime pieces this feature should reuse:

- SQLAlchemy storage models and Alembic migrations.
- FastAPI routes protected by the existing optional token auth.
- `job_runs`, `job_events`, queued/inline execution, cancellation, and SSE progress streaming.
- Workflow audit history through `workflow_runs`.
- Market data storage and provider-backed sync.
- Persistent paper trading, broker adapter safety boundaries, and broker order audit rows.

Legacy AI functionality lives outside the new runtime:

- `legacy/skills/quant-analysis/SKILL.md` describes DeepSeek-backed market-analysis reports.
- `legacy/skills/quant-strategy/SKILL.md` describes AI strategy generation and review.
- `legacy/django_app/strategies/views.py` directly calls DeepSeek and stores generated Python code.

Quant Agent v1 migrates the useful research workflow into the new package without carrying over unsafe arbitrary-code generation.

## Non-Goals

- No real broker or exchange orders.
- No broker adapter calls.
- No automatic paper run creation.
- No automatic strategy approval.
- No execution of LLM-generated Python code.
- No generated strategy modules written to disk.
- No storage of API keys, raw provider credentials, or unbounded prompts/responses.
- No live tick streaming or real-time monitoring agent.
- No portfolio advice framed as guaranteed returns, price targets, or direct buy/sell instructions.

## User-Facing Capabilities

### Market Analysis Agent

Input:

- `symbol`
- optional `start` and `end` dates
- optional `lookback_bars`, default `252`, minimum `60`, maximum `1000`
- optional `mode`, initially `overview`, `risk`, or `regime`

Behavior:

1. Load existing normalized daily bars from the database.
2. Validate that enough data exists for the requested analysis.
3. Compute deterministic metrics before calling the LLM:
   - data source, date range, bar count, latest close
   - 1-month and 3-month return when enough history exists
   - 20-day volatility
   - 20-day and 60-day moving-average trend
   - 20-day average volume
   - 52-week high/low when enough history exists
   - simple support/resistance levels from recent highs/lows
   - risk observations such as drawdown and volatility regime
4. Ask the LLM to write a concise Chinese research report grounded only in those computed metrics.
5. Persist an audited agent run and return a structured result.

Output:

- `agent_run_id`
- `agent_type="market_analysis"`
- `symbol`, date range, bar count
- computed metrics payload
- report text
- `research_only=true`
- disclaimer text

### Strategy Idea Agent

Input:

- natural-language `idea`, required and capped at `4000` characters
- optional `symbol`
- optional `market_context` text, capped at `2000` characters
- optional `constraints`, such as max holding period or long-only

Behavior:

1. Validate and cap the input.
2. Ask the LLM to convert the idea into a structured strategy specification, not executable code.
3. Require the output to cover:
   - thesis
   - market regime assumption
   - entry rules
   - exit rules
   - risk controls
   - parameters to test
   - data requirements
   - failure modes
   - backtest readiness notes
4. Persist an audited agent run and return the structured specification.

Output:

- `agent_run_id`
- `agent_type="strategy_idea"`
- structured strategy spec payload
- narrative summary
- `research_only=true`
- disclaimer text

## Architecture

Add a new package:

```text
src/quant_trading/agents/
  __init__.py
  llm.py
  models.py
  market_analysis.py
  strategy_idea.py
  service.py
```

### `agents.llm`

Defines:

- `LLMClient` protocol with `complete(prompt: str) -> LLMResponse`.
- `LLMResponse` dataclass with `content`, `model`, and optional token metadata.
- `DeepSeekLLMClient`, created from environment/settings.
- `FakeLLMClient` for tests.

The DeepSeek client should be lazily imported so tests and local runs without the optional package still import cleanly. If an agent job needs a real LLM but `DEEPSEEK_API_KEY` is missing, the job must fail with a clear, capped error message.

### `agents.models`

Defines stable in-process data structures:

- `AgentRunStatus`: `running`, `succeeded`, `failed`.
- `AgentType`: `market_analysis`, `strategy_idea`.
- `MarketAnalysisRequest`
- `StrategyIdeaRequest`
- `AgentResult`

Use Python dataclasses for service-layer models. Use Pydantic models only at FastAPI route boundaries, matching the current API style.

### `agents.market_analysis`

Owns deterministic metric computation and prompt construction. The LLM prompt must include only bounded computed metrics and a bounded context summary, not raw full market data.

The report prompt must explicitly require:

- historical-data-only language
- no future price prediction
- no direct buy/sell recommendation
- confidence qualifiers such as "shows", "suggests", or "indicates"
- concise Chinese output

### `agents.strategy_idea`

Owns strategy-spec prompt construction and response parsing. The prompt must request a JSON object with the required strategy-spec fields. If parsing fails but a bounded narrative response exists, the service may still mark the run succeeded with `parsed=false` and store the bounded narrative in `result_payload`.

The prompt must explicitly prohibit:

- executable code output
- external libraries
- broker or order execution instructions
- claims of profitability
- direct live-trading recommendations

### `agents.service`

Coordinates persistence and execution:

- create running `agent_runs` row
- execute the selected agent
- mark succeeded or failed
- sanitize and cap persisted payloads
- expose functions used by `jobs.runtime`

Expected service functions:

- `run_market_analysis_agent(engine, request, llm_client=None, job_run_id=None) -> dict`
- `run_strategy_idea_agent(engine, request, llm_client=None, job_run_id=None) -> dict`

## Storage

Add `AgentRunORM` in `storage.models`.

Table: `agent_runs`

Columns:

- `id` integer primary key
- `agent_type` string indexed
- `status` string indexed
- `symbol` nullable string indexed
- `model_name` string
- `request_payload` text
- `metrics_payload` text
- `result_payload` text
- `error_message` nullable string
- `job_run_id` nullable integer indexed
- `started_at` datetime
- `finished_at` nullable datetime
- `duration_ms` nullable integer
- `created_at` datetime

Add `AgentRunRepository` in `storage.repositories`:

- `create_running(...)`
- `mark_succeeded(...)`
- `mark_failed(...)`
- `list_recent(agent_type=None, status=None, symbol=None, limit=50)`
- `get(agent_run_id)`

All stored JSON payloads must use the existing compact JSON style and cap long fields. No raw API token or full LLM provider response should be stored.
Payload caps are fixed in v1: request payload values at `4000` characters, prompt text at `8000` characters when stored for debugging, result payload values at `12000` characters, and errors at `1000` characters.

Add Alembic migration:

```text
migrations/versions/20260624_0007_add_agent_runs.py
```

The migration creates `agent_runs` and indexes for `agent_type`, `status`, `symbol`, and `job_run_id`.

## Job Runtime

Extend `quant_trading.jobs.runtime`:

- `AGENT_MARKET_ANALYSIS = "agent_market_analysis"`
- `AGENT_STRATEGY_IDEA = "agent_strategy_idea"`
- include both in `SUPPORTED_JOB_TYPES`
- route both through `_execute_payload()`

Execution should use existing `job_runs` and `job_events` behavior:

- job starts as queued/running as it does today
- agent service creates and updates `agent_runs`
- job result contains `agent_run_id`, status, and a summarized result
- failed jobs mark both `job_runs` and `agent_runs` as failed when an agent row exists

Cancellation only needs cooperative checks before the LLM call in v1. Mid-call cancellation is not required.

## API

Extend `api.routes.jobs`:

- `POST /jobs/agents/market-analysis`
- `POST /jobs/agents/strategy-idea`

Request validation:

- `symbol` required for market analysis, max 32 chars
- `idea` required for strategy idea, max 4000 chars
- optional dates must be ISO date strings
- `lookback_bars` must be between 60 and 1000

Add route module:

```text
src/quant_trading/api/routes/agents.py
```

Routes:

- `GET /agent-runs`
- `GET /agent-runs/{agent_run_id}`

Responses include parsed JSON payloads and ISO timestamps, following existing route style.

Register the new route in `api.main`.

## Configuration

Extend `AppSettings` with:

- `deepseek_api_key`
- `deepseek_api_base`, default `https://api.deepseek.com`
- `deepseek_model`, default `deepseek-v4-pro`
- `agent_prompt_max_chars`, default `8000`
- `agent_result_max_chars`, default `12000`

Settings must not expose secrets through API responses or persisted payloads.

## Data Flow

Market analysis:

```text
POST /jobs/agents/market-analysis
-> submit_job_run(agent_market_analysis)
-> execute_job_run()
-> run_market_analysis_agent()
-> AgentRunRepository.create_running()
-> MarketDataRepository.list_bars()
-> compute metrics
-> LLMClient.complete()
-> AgentRunRepository.mark_succeeded()
-> JobRunRepository.mark_succeeded()
-> GET /agent-runs/{id}
```

Strategy idea:

```text
POST /jobs/agents/strategy-idea
-> submit_job_run(agent_strategy_idea)
-> execute_job_run()
-> run_strategy_idea_agent()
-> AgentRunRepository.create_running()
-> LLMClient.complete()
-> parse or store structured response
-> AgentRunRepository.mark_succeeded()
-> JobRunRepository.mark_succeeded()
-> GET /agent-runs/{id}
```

## Error Handling

- Missing bars: fail with `no market bars found for symbol: <symbol>`.
- Insufficient bars: fail with a clear message containing required and actual counts.
- Missing LLM credentials: fail with `DEEPSEEK_API_KEY is required for agent jobs`.
- LLM import error: fail with a clear package/configuration message.
- LLM response parse error: strategy idea may still succeed if a bounded raw report is available; market analysis should store the narrative report as text.
- Any persisted `error_message` is capped at 1000 characters.

## Safety Requirements

- Every successful output includes `research_only=true`.
- Every successful output includes a disclaimer.
- Prompts explicitly prohibit buy/sell recommendations, price targets, guaranteed returns, and live trading instructions.
- No generated Python code is accepted as a v1 success condition.
- No agent job can call paper trading, workflow paper commands, or broker adapter APIs.
- API keys and auth tokens must not appear in `request_payload`, `result_payload`, `metrics_payload`, logs, or errors.
- LLM prompts use summarized metrics, not full raw time series.

## Testing

Unit tests:

- `FakeLLMClient` returns deterministic responses.
- market metrics are computed from known bars.
- market-analysis prompt contains required safety constraints.
- strategy-idea prompt prohibits code and live trading.
- long request/result/error text is capped.

Integration tests:

- `AgentRunRepository` creates, succeeds, fails, lists, and gets runs.
- Alembic migration creates `agent_runs`.
- market-analysis job creates `job_runs`, `job_events`, and `agent_runs`.
- strategy-idea job creates `job_runs`, `job_events`, and `agent_runs`.
- `/agent-runs` and `/agent-runs/{id}` return parsed payloads.
- missing market data fails cleanly and persists failure state.
- missing LLM credentials fail cleanly.
- optional token auth protects the new endpoints consistently with existing routes.

Non-regression tests:

- existing job types still run.
- existing dashboard and job API tests still pass.
- no broker order event is created by agent jobs.

## Documentation

Update README with:

- Quant Agent v1 overview.
- endpoints and example curl commands.
- research-only safety notes.
- required DeepSeek environment variables.
- statement that strategy-code generation and automatic trading are intentionally excluded from v1.

## Implementation Notes

Implementation should start from `main` in an isolated branch. Existing local changes on the older `django-app` checkout must not be modified.

Use test-driven development:

1. Add failing tests for storage and service behavior.
2. Add schema and repository support.
3. Add agent modules and fake LLM tests.
4. Add job runtime and route tests.
5. Add README documentation.

After implementation, run the targeted test suite first, then the full `python -m pytest tests -q` if dependencies are available.
