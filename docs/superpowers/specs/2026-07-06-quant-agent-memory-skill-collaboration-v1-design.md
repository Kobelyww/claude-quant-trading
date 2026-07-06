# Quant Agent Memory, Skills, And Collaboration v1 Design

## Purpose

Quant Agent now has a research-only strategy loop, human candidate approval,
deterministic research validation, backtest review, and a pre-live safety layer.
Those pieces make the platform safer, but the agent still behaves mostly like a
linear workflow. It can record what happened, yet it cannot reliably reuse what it
learned, choose among versioned strategy skills, or coordinate several specialist
opinions before recommending the next research action.

This milestone adds the first productized agent operating model:

- A durable learning ledger that turns completed runs, approvals, rejections,
  validation failures, and safety incidents into reusable research memory.
- A versioned strategy skill registry that describes what each strategy template can
  do, what data it requires, and what validation boundaries apply.
- A multi-agent review board protocol that produces structured, auditable votes from
  specialist reviewers before a coordinator recommends a next action.

The system remains research and paper-only. It must not execute generated code, place
live orders, add broker credentials, or automatically promote research output to paper
or live execution.

## Current Context

Verified on 2026-07-06 after local `main` fast-forward to `1e17f72`.

The platform already has:

- `agent_runs` for audited `market_analysis`, `strategy_idea`, and
  `backtest_review` runs.
- `agent_candidate_reviews` for human approval or rejection of generated research
  candidates.
- `data_quality_reports` and `research_validation_reports` for deterministic data
  and research checks.
- `execution_order_intents`, `execution_order_decisions`,
  `operator_approval_requests`, `safety_incidents`, and kill-switch events for
  pre-live operational safety.
- Parser and safety checks that reject executable code, live trading language, broker
  instructions, and profitability claims in strategy and backtest review outputs.
- A currently narrow strategy candidate path centered on the deterministic `ma_cross`
  template.

The remaining gap is that these artifacts are treated as history, not reusable
experience. A rejected candidate does not become a future warning. A failed validation
does not prevent a nearly identical candidate from being proposed again. Strategy
templates are not represented as first-class, versioned skills. Review output is
mostly embedded in each agent run instead of being normalized into specialist votes
that a coordinator can reason over.

## Design Goals

1. Reuse prior research outcomes without giving the LLM authority to bypass safety
   gates.
2. Make strategy skills first-class, versioned, auditable records.
3. Turn specialist reviews into structured votes with explicit blocking reasons.
4. Keep every memory and review trace linked back to source artifacts.
5. Preserve deterministic validation as the source of truth for readiness floors.
6. Avoid large abstractions that imply a general live-trading agent.

## Non-Goals

This milestone does not include:

- Real broker or exchange APIs.
- Live order placement or broker credentials.
- Generated strategy code execution.
- LLM-written strategy modules.
- Automatic strategy approval.
- Automatic paper run creation from an agent recommendation.
- Automatic promotion from paper research to live trading.
- Vector database infrastructure.
- Cross-user personalization.
- Reinforcement learning or online model training.
- A broad prompt editor UI.
- A general marketplace for arbitrary user-uploaded skills.

## Approaches Considered

### A. Prompt-only memory

Append recent agent run summaries to future prompts.

This is simple, but it is not product-grade. It has no durable schema, no source
traceability, no expiry, and no way to distinguish operator decisions from LLM text.
It also increases prompt size without creating auditable learning records.

### B. Durable learning ledger plus explicit retrieval

Persist normalized memory items derived from approved source artifacts. Retrieve a
small, filtered set of memories for future agent prompts and coordinator decisions.
Each memory has a type, source artifact, confidence, expiry, and safety classification.

This is the recommended approach. It fits the current SQLAlchemy storage model, keeps
memory auditable, and allows deterministic services to decide what may enter prompts.

### C. External vector memory from day one

Store embeddings for every artifact and use semantic retrieval.

This will be useful later, but it adds operational complexity before the memory schema
and safety rules are stable. V1 should support a future embedding column or adapter,
but the first retrieval path should be deterministic SQL filtering and scoring.

## Chosen Architecture

Implement approach B with a small skill registry and review board layer.

```text
agent run / candidate review / validation report / safety incident
  -> learning extractor
  -> agent_learning_memories
  -> memory retrieval service
  -> prompt context bundle
  -> specialist review board
  -> coordinator recommendation
  -> existing human approval / validation / safety gates
```

The LLM may consume memory and specialist votes, but it may not mutate memory directly.
Only deterministic extractors and operator actions can create or retire learning
records.

## Data Model

### `agent_learning_memories`

Stores durable, reusable lessons extracted from prior artifacts.

Fields:

- `id`: integer primary key.
- `memory_type`: string, indexed. Allowed values:
  - `strategy_failure`
  - `strategy_success`
  - `data_quality_lesson`
  - `risk_lesson`
  - `operator_decision`
  - `safety_incident_lesson`
- `scope`: string, indexed. Initial values: `global`, `symbol`, `strategy_skill`.
- `symbol`: nullable string, indexed.
- `strategy_skill_id`: nullable foreign key to `strategy_skills.id`, indexed.
- `source_type`: string, indexed. Allowed values:
  - `agent_run`
  - `candidate_review`
  - `data_quality_report`
  - `research_validation_report`
  - `execution_order_decision`
  - `safety_incident`
  - `operator_approval_request`
- `source_id`: integer, indexed.
- `title`: string, capped to 160 characters.
- `content`: text, capped to 4000 characters.
- `reason_code`: string, indexed.
- `evidence_payload`: JSON text, capped to 12000 characters.
- `confidence`: decimal between `0` and `1`.
- `importance`: decimal between `0` and `1`, indexed.
- `status`: string, indexed. Allowed values: `active`, `retired`.
- `expires_at`: nullable datetime, indexed.
- `created_at`: datetime, indexed.
- `created_by`: string, capped to 128 characters. Initial values: `system`,
  `operator`.
- `retired_at`: nullable datetime.
- `retired_by`: nullable string, capped to 128 characters.
- `retired_reason`: nullable text, capped to 1000 characters.

Uniqueness:

- A partial unique index must prevent duplicate active memories for the same
  `(memory_type, source_type, source_id, reason_code)`.

Safety rules:

- `content` must not contain live trading instructions, broker instructions,
  executable code blocks, or profitability guarantees.
- Memories sourced from LLM output must include a deterministic source artifact and
  must pass the same unsafe text scanner used by backtest review.
- Memory retrieval must not expose raw operator notes if they contain secrets or API
  keys. Reuse the existing error/message sanitization style.

### `strategy_skills`

Stores versioned strategy skill definitions.

Fields:

- `id`: integer primary key.
- `skill_key`: string, indexed. Example: `ma_cross`.
- `version`: string, indexed. Example: `1.0.0`.
- `display_name`: string.
- `description`: text.
- `status`: string, indexed. Allowed values: `active`, `deprecated`, `disabled`.
- `template_type`: string. Initial value: `deterministic_template`.
- `supported_markets_payload`: JSON text.
- `required_data_fields_payload`: JSON text.
- `parameter_schema_payload`: JSON text.
- `validation_rules_payload`: JSON text.
- `risk_notes_payload`: JSON text.
- `prompt_guidance`: text, capped to 4000 characters.
- `created_at`: datetime, indexed.
- `updated_at`: datetime, indexed.

Uniqueness:

- `(skill_key, version)` must be unique.

Initial seed:

- `skill_key="ma_cross"`
- `version="1.0.0"`
- `template_type="deterministic_template"`
- Required fields: `open`, `high`, `low`, `close`, `volume`, `timestamp`, `symbol`.
- Parameters:
  - `short_window`: positive integer
  - `long_window`: positive integer greater than `short_window`
  - `order_size`: positive integer
  - `initial_cash`: finite decimal string greater than `0`
- Validation rules:
  - data quality report must not be failed
  - research validation readiness floor caps backtest review readiness
  - no generated executable code
  - no live trading recommendation

### `agent_review_board_runs`

Stores one multi-specialist review board run.

Fields:

- `id`: integer primary key.
- `subject_type`: string, indexed. Initial values:
  - `strategy_candidate`
  - `backtest_review`
  - `research_validation_report`
- `subject_id`: integer, indexed.
- `status`: string, indexed. Allowed values: `running`, `completed`, `failed`.
- `coordinator_agent_run_id`: nullable foreign key to `agent_runs.id`.
- `final_recommendation`: string, indexed. Allowed values:
  - `reject`
  - `needs_more_research`
  - `ready_for_human_backtest_approval`
  - `ready_for_paper_research_consideration`
- `blocking_reason_codes_payload`: JSON text.
- `memory_ids_payload`: JSON text.
- `summary_payload`: JSON text.
- `created_at`: datetime, indexed.
- `finished_at`: nullable datetime.
- `duration_ms`: nullable integer.

### `agent_review_board_votes`

Stores each specialist vote.

Fields:

- `id`: integer primary key.
- `board_run_id`: foreign key to `agent_review_board_runs.id`, indexed.
- `reviewer_role`: string, indexed. Initial roles:
  - `data_steward`
  - `strategy_researcher`
  - `risk_officer`
  - `validation_reviewer`
  - `operations_reviewer`
- `agent_run_id`: nullable foreign key to `agent_runs.id`.
- `vote`: string, indexed. Allowed values:
  - `block`
  - `needs_review`
  - `pass`
- `reason_code`: string, indexed.
- `rationale`: text, capped to 2000 characters.
- `evidence_payload`: JSON text, capped to 12000 characters.
- `created_at`: datetime, indexed.

The coordinator must treat any `block` vote as a hard cap on the final
recommendation. The coordinator may not upgrade a deterministic readiness floor.

## Services

### `LearningMemoryService`

Responsibilities:

1. Extract deterministic memory candidates from existing artifacts.
2. Validate memory safety and payload bounds.
3. Persist idempotent memories.
4. Retire stale or superseded memories.
5. Retrieve bounded memory bundles for prompts and review boards.

Public API shape:

```python
class LearningMemoryService:
    def extract_from_candidate_review(self, candidate_review_id: int) -> list[MemoryResult]: ...
    def extract_from_validation_report(self, report_id: int) -> list[MemoryResult]: ...
    def extract_from_safety_incident(self, incident_id: int) -> list[MemoryResult]: ...
    def retrieve(
        self,
        *,
        symbol: str | None,
        strategy_skill_id: int | None,
        memory_types: list[str],
        limit: int = 8,
    ) -> list[MemoryPayload]: ...
    def retire(self, memory_id: int, *, operator: str, reason: str) -> MemoryPayload: ...
```

Extraction rules:

- Rejected candidate reviews create `operator_decision` memories.
- Failed or needs-review research validation reports create `strategy_failure` or
  `data_quality_lesson` memories.
- Passed validation reports may create `strategy_success` memories, but only with
  conservative language and `confidence <= 0.7`.
- Safety incidents create `safety_incident_lesson` memories.
- Backtest review LLM text can inform the summary, but deterministic report fields
  must provide the source evidence.

Retrieval scoring:

- Active status only.
- Not expired.
- Exact symbol match outranks global memories.
- Exact strategy skill match outranks global strategy memories.
- Higher importance outranks lower importance.
- Newer memories break ties.
- Result bundle must be capped by count and total character budget.

### `StrategySkillRegistry`

Responsibilities:

1. Seed and read versioned strategy skill definitions.
2. Validate strategy candidate payloads against the selected skill.
3. Provide prompt guidance for strategy generation.
4. Preserve backward compatibility with the existing `ma_cross` validation path.

Public API shape:

```python
class StrategySkillRegistry:
    def get_active(self, skill_key: str) -> StrategySkillPayload: ...
    def list_active(self) -> list[StrategySkillPayload]: ...
    def validate_candidate(self, payload: dict, *, request_symbol: str | None) -> SkillValidationResult: ...
```

V1 must support only `ma_cross` for executable backtest submission. Adding the
registry must not imply arbitrary strategy execution.

### `ReviewBoardService`

Responsibilities:

1. Build a bounded context package from source artifacts, skill metadata, validation
   reports, and retrieved memories.
2. Run deterministic specialist checks where possible.
3. Optionally call LLM reviewers for narrative rationale, with strict JSON parsing and
   unsafe text scanning.
4. Persist specialist votes.
5. Produce a coordinator recommendation that cannot exceed deterministic caps.

Initial specialist responsibilities:

- `data_steward`: data quality status, stale data, missing bars, invalid OHLCV.
- `strategy_researcher`: thesis clarity, supported skill, parameter sanity.
- `risk_officer`: drawdown, exposure assumptions, risk controls, overfit warnings.
- `validation_reviewer`: out-of-sample, walk-forward, sensitivity, benchmark.
- `operations_reviewer`: safety posture, pending incidents, kill switch, approval gaps.

Coordinator rules:

- Any failed data quality report caps final recommendation at `reject`.
- Any research validation readiness floor of `not_ready` caps final recommendation at
  `needs_more_research`.
- Any `block` vote caps final recommendation at `needs_more_research` or lower.
- No recommendation may instruct paper trading creation, broker submission, or live
  execution.
- `ready_for_paper_research_consideration` means human-reviewed paper research only.

## Prompt And Context Changes

### Strategy idea prompt

Add a bounded memory and skill context section:

```text
Relevant research memories:
- [memory_type/reason_code] summary

Available strategy skills:
- ma_cross v1.0.0: deterministic moving-average crossover template
```

The prompt must instruct the model to choose only from active strategy skills and to
return the selected `strategy_skill_key` and `strategy_skill_version`.

### Backtest review prompt

Add memory context only after deterministic validation context. The model may use
memory to explain repeated failure patterns, but it may not override validation floors.

### Review board prompts

Each specialist prompt must return one JSON object:

```json
{
  "vote": "block|needs_review|pass",
  "reason_code": "snake_case_reason",
  "rationale": "bounded research-only explanation",
  "evidence": {}
}
```

Invalid JSON, unsafe text, or unsupported vote values must produce a deterministic
`needs_review` vote with `reason_code="invalid_reviewer_output"`.

## API Surface

Add read-first APIs under existing auth middleware:

- `GET /agents/skills`
- `GET /agents/skills/{skill_key}`
- `GET /agents/memories`
- `POST /agents/memories/{memory_id}/retire`
- `GET /agents/review-board-runs`
- `GET /agents/review-board-runs/{run_id}`

Add command APIs:

- `POST /agents/candidate-reviews/{id}/extract-memories`
- `POST /agents/research-validation-reports/{id}/extract-memories`
- `POST /agents/candidate-reviews/{id}/review-board`

Command APIs must require auth when auth is enabled. They must not submit backtest jobs,
paper runs, broker calls, or order intents.

## Dashboard

Add a compact `Agent Intelligence` dashboard section using the existing server-rendered
table style.

Display:

- Active strategy skills.
- Recent learning memories.
- Recent review board runs.
- Vote counts by role and vote.
- Recent retired memories.

Do not add a large visual redesign. Keep the page operational and dense.

## Safety And Governance

- Memory is advisory context, not authority.
- Deterministic validation and safety services always outrank memory and LLM reviewer
  text.
- Operator approvals remain explicit and separate from agent recommendations.
- Every memory must link to source evidence.
- Every review board vote must have a reason code.
- No endpoint may expose secrets, raw tracebacks, broker credentials, or live execution
  paths.
- No LLM output may create executable strategy code.

## Migration And Backward Compatibility

The migration must:

1. Add the four new tables.
2. Seed `ma_cross` skill version `1.0.0`.
3. Leave existing `agent_runs`, candidate reviews, validation reports, paper runs, and
   safety tables unchanged.

Existing APIs must keep working. Existing strategy idea validation may delegate to the
new skill registry, but response payloads must remain backward compatible:

- `candidate_payload`
- `backtest_request_payload`
- `requires_human_approval`
- `validation_status`
- `validation_errors`
- `safety_flags`

New fields such as `strategy_skill_key`, `strategy_skill_version`, and `memory_ids`
may be added as optional fields.

## Testing Strategy

Unit tests:

- Skill registry seed and validation.
- Memory extraction from rejected candidate reviews.
- Memory extraction from failed and passed research validation reports.
- Unsafe memory text rejection.
- Memory retrieval scoring and budget caps.
- Review board vote parsing and invalid-output fallback.
- Coordinator cap rules.

Integration tests:

- Migration tables, indexes, uniqueness, and `ma_cross` seed.
- Repository lifecycle for skills, memories, board runs, and votes.
- Candidate review memory extraction API.
- Research validation memory extraction API.
- Review board API and persisted votes.
- Auth protection for command APIs.
- Dashboard rendering and escaping.

Regression tests:

- Existing strategy idea candidate approval flow still works.
- Existing backtest review readiness caps still apply.
- Existing pre-live safety readiness still reports no live execution.
- Existing full test suite continues to pass.

## Rollout Plan

Phase 1: Storage and repositories.

Phase 2: Skill registry seeded with `ma_cross` and wired into candidate validation.

Phase 3: Learning memory extraction and retrieval.

Phase 4: Review board persistence and deterministic coordinator.

Phase 5: Optional LLM specialist reviewer prompts with strict parser fallback.

Phase 6: APIs, dashboard, README, and full verification.

## Initial Product Defaults

V1 uses these defaults:

- Default memory expiry: 180 days for symbol-specific memories, no expiry for retired
  operator decisions unless manually retired.
- Maximum retrieved memories per prompt: 8.
- Maximum memory context characters per prompt: 3000.
- Minimum memory confidence for prompt inclusion: `0.4`.
- Initial review board subject: candidate reviews with linked research validation
  reports.

Future milestones may tune these defaults after the system records enough operator
feedback, but V1 implementation must use them unless a later approved spec changes
them.
