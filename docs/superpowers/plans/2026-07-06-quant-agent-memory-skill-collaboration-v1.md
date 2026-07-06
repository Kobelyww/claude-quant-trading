# Quant Agent Memory, Skills, And Collaboration v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable learning memory ledger, versioned strategy skill registry, and structured multi-agent review board for Quant Agent while preserving the research-only and paper-only safety boundary.

**Architecture:** Add storage and repositories first, then build focused services under `quant_trading.agents` for skill lookup, memory extraction/retrieval, shared unsafe-output scanning, and review board coordination. Wire the services into existing candidate validation and expose read/command APIs plus a compact dashboard section without allowing generated code execution, paper-run creation, broker calls, or live trading.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, Pydantic, pytest, existing Quant Trading storage/job/agent patterns.

---

## Branch And Scope Notes

- Working directory: `/Users/haobowang/Desktop/Code file/Python/LLM-Study/quant-trading/.worktrees/quant-agent-memory-skill-collaboration-v1`
- Working branch: `codex/quant-agent-memory-skill-collaboration-v1`
- Design spec: `docs/superpowers/specs/2026-07-06-quant-agent-memory-skill-collaboration-v1-design.md`
- This milestone remains research and paper-only.
- Do not add broker SDKs, exchange APIs, credentials, live order placement, live polling/webhooks, generated strategy execution, automatic strategy approval, or automatic paper-run creation.
- Existing main worktree has unrelated local edits on `django-app`; do not touch it.

## Required Review Protocol

After every implementation task:

1. **Spec review:** Compare the actual diff against `docs/superpowers/specs/2026-07-06-quant-agent-memory-skill-collaboration-v1-design.md`. Confirm all task requirements are covered and no live/paper automation slipped in.
2. **Quality review:** Check state transitions, transaction boundaries, JSON payload caps, unsafe text handling, auth behavior, dashboard escaping, test quality, and backward compatibility.

Do not proceed to the next task until both reviews pass.

## File Structure

- Modify: `src/quant_trading/storage/models.py`
  - Add `StrategySkillORM`, `AgentLearningMemoryORM`, `AgentReviewBoardRunORM`, and `AgentReviewBoardVoteORM`.
- Modify: `src/quant_trading/storage/repositories.py`
  - Add repositories for strategy skills, learning memories, review board runs, and review board votes.
- Create: `migrations/versions/20260706_0011_add_agent_memory_skill_review_board.py`
  - Add four tables and seed `ma_cross` skill `1.0.0`.
- Modify: `tests/integration/test_migrations.py`
  - Assert schema, indexes, uniqueness, and seed.
- Create: `tests/integration/test_agent_intelligence_repositories.py`
  - Cover repository lifecycle, idempotent memory creation, retrieval filters, retirement, board runs, and votes.
- Create: `src/quant_trading/agents/skills.py`
  - Define `StrategySkillRegistry`, skill payload types, and candidate validation bridge.
- Modify: `src/quant_trading/agents/candidates.py`
  - Delegate `ma_cross` validation to skill metadata while preserving response shape.
- Modify: `src/quant_trading/agents/service.py`
  - Load active skill metadata when validating `strategy_idea` output.
- Create: `tests/unit/test_strategy_skill_registry.py`
  - Cover seeded skill validation and candidate payload compatibility.
- Create: `src/quant_trading/agents/output_safety.py`
  - Centralize unsafe LLM output scanning shared by backtest review and memory services.
- Modify: `src/quant_trading/agents/backtest_review.py`
  - Use shared unsafe scanner.
- Create: `src/quant_trading/agents/memory.py`
  - Define `LearningMemoryService`, memory payloads, extraction, retrieval, retirement, and safety checks.
- Create: `tests/unit/test_agent_learning_memory.py`
  - Cover extraction and retrieval rules.
- Create: `src/quant_trading/agents/review_board.py`
  - Define `ReviewBoardService`, deterministic specialist votes, coordinator caps, and strict reviewer-output parsing.
- Create: `tests/unit/test_agent_review_board.py`
  - Cover vote parsing and coordinator rules.
- Create: `src/quant_trading/api/routes/agent_intelligence.py`
  - Expose skills, memories, review board runs, and command endpoints.
- Modify: `src/quant_trading/api/main.py`
  - Register the new router.
- Modify: `src/quant_trading/api/routes/dashboard.py`
  - Add compact `Agent Intelligence` section.
- Create: `tests/integration/test_agent_intelligence_api.py`
  - Cover read APIs, command APIs, auth behavior, and error mapping.
- Modify: `tests/integration/test_dashboard.py`
  - Assert dashboard section, escaping, and empty states.
- Modify: `README.md`
  - Document memory, skill registry, review board, safety boundaries, and endpoints.

## Task 1: Storage, Migration, And Repositories

**Files:**
- Modify: `src/quant_trading/storage/models.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `migrations/versions/20260706_0011_add_agent_memory_skill_review_board.py`
- Modify: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_agent_intelligence_repositories.py`

- [ ] **Step 1: Write failing migration assertions**

Add `_assert_agent_intelligence_schema(inspector)` to `tests/integration/test_migrations.py` and call it from the existing migration schema test.

```python
def _assert_agent_intelligence_schema(inspector) -> None:
    tables = set(inspector.get_table_names())
    assert {
        "strategy_skills",
        "agent_learning_memories",
        "agent_review_board_runs",
        "agent_review_board_votes",
    } <= tables

    skill_columns = _columns(inspector, "strategy_skills")
    assert {
        "id",
        "skill_key",
        "version",
        "display_name",
        "description",
        "status",
        "template_type",
        "supported_markets_payload",
        "required_data_fields_payload",
        "parameter_schema_payload",
        "validation_rules_payload",
        "risk_notes_payload",
        "prompt_guidance",
        "created_at",
        "updated_at",
    } <= set(skill_columns)
    assert skill_columns["skill_key"]["nullable"] is False
    assert skill_columns["version"]["nullable"] is False
    skill_uniques = _unique_columns(inspector, "strategy_skills")
    assert skill_uniques["uq_strategy_skills_key_version"] == ("skill_key", "version")

    memory_columns = _columns(inspector, "agent_learning_memories")
    assert {
        "id",
        "memory_type",
        "scope",
        "symbol",
        "strategy_skill_id",
        "source_type",
        "source_id",
        "title",
        "content",
        "reason_code",
        "evidence_payload",
        "confidence",
        "importance",
        "status",
        "expires_at",
        "created_at",
        "created_by",
        "retired_at",
        "retired_by",
        "retired_reason",
    } <= set(memory_columns)
    assert memory_columns["memory_type"]["nullable"] is False
    assert memory_columns["source_id"]["nullable"] is False

    board_columns = _columns(inspector, "agent_review_board_runs")
    assert {
        "id",
        "subject_type",
        "subject_id",
        "status",
        "coordinator_agent_run_id",
        "final_recommendation",
        "blocking_reason_codes_payload",
        "memory_ids_payload",
        "summary_payload",
        "created_at",
        "finished_at",
        "duration_ms",
    } <= set(board_columns)

    vote_columns = _columns(inspector, "agent_review_board_votes")
    assert {
        "id",
        "board_run_id",
        "reviewer_role",
        "agent_run_id",
        "vote",
        "reason_code",
        "rationale",
        "evidence_payload",
        "created_at",
    } <= set(vote_columns)
```

- [ ] **Step 2: Run migration test to verify it fails**

Run:

```bash
pytest tests/integration/test_migrations.py -q
```

Expected: FAIL because `strategy_skills`, `agent_learning_memories`, `agent_review_board_runs`, and `agent_review_board_votes` do not exist.

- [ ] **Step 3: Add ORM models**

Add these imports to `src/quant_trading/storage/models.py` if missing:

```python
from sqlalchemy import Boolean, Index, Text, text
```

Add model classes after `ResearchValidationReportORM` and before operations safety tables:

```python
class StrategySkillORM(Base):
    __tablename__ = "strategy_skills"
    __table_args__ = (
        UniqueConstraint("skill_key", "version", name="uq_strategy_skills_key_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    template_type: Mapped[str] = mapped_column(String(64), default="deterministic_template")
    supported_markets_payload: Mapped[str] = mapped_column(Text, default="[]")
    required_data_fields_payload: Mapped[str] = mapped_column(Text, default="[]")
    parameter_schema_payload: Mapped[str] = mapped_column(Text, default="{}")
    validation_rules_payload: Mapped[str] = mapped_column(Text, default="{}")
    risk_notes_payload: Mapped[str] = mapped_column(Text, default="{}")
    prompt_guidance: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AgentLearningMemoryORM(Base):
    __tablename__ = "agent_learning_memories"
    __table_args__ = (
        Index(
            "uq_agent_learning_memories_active_source_reason",
            "memory_type",
            "source_type",
            "source_id",
            "reason_code",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    strategy_skill_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_skills.id"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    reason_code: Mapped[str] = mapped_column(String(128), index=True)
    evidence_payload: Mapped[str] = mapped_column(Text, default="{}")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0)
    importance: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="system")
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retired_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retired_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentReviewBoardRunORM(Base):
    __tablename__ = "agent_review_board_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(64), index=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    coordinator_agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    final_recommendation: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    blocking_reason_codes_payload: Mapped[str] = mapped_column(Text, default="[]")
    memory_ids_payload: Mapped[str] = mapped_column(Text, default="[]")
    summary_payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AgentReviewBoardVoteORM(Base):
    __tablename__ = "agent_review_board_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_run_id: Mapped[int] = mapped_column(ForeignKey("agent_review_board_runs.id"), index=True)
    reviewer_role: Mapped[str] = mapped_column(String(64), index=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    vote: Mapped[str] = mapped_column(String(32), index=True)
    reason_code: Mapped[str] = mapped_column(String(128), index=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence_payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
```

- [ ] **Step 4: Add Alembic migration**

Create `migrations/versions/20260706_0011_add_agent_memory_skill_review_board.py`.

Use the previous migration's revision id as `down_revision`. Create the four tables and insert the `ma_cross` seed:

```python
MA_CROSS_SKILL = {
    "skill_key": "ma_cross",
    "version": "1.0.0",
    "display_name": "MA Cross",
    "description": "Deterministic moving-average crossover research template.",
    "status": "active",
    "template_type": "deterministic_template",
    "supported_markets_payload": '["A_STOCK"]',
    "required_data_fields_payload": '["open","high","low","close","volume","timestamp","symbol"]',
    "parameter_schema_payload": '{"short_window":{"type":"positive_int"},"long_window":{"type":"positive_int_gt_short_window"},"order_size":{"type":"positive_int"},"initial_cash":{"type":"positive_decimal_string"}}',
    "validation_rules_payload": '{"no_generated_code":true,"no_live_trading_recommendation":true,"readiness_floor_caps_review":true}',
    "risk_notes_payload": '{"template_risks":["trend-following lag","sideways whipsaw","parameter overfit"]}',
    "prompt_guidance": "Use only for deterministic moving-average crossover research. Do not output executable code or trading instructions.",
}
```

Expected migration behavior:

- `upgrade()` creates all four tables, indexes, unique constraints, and seed row.
- `downgrade()` drops `agent_review_board_votes`, `agent_review_board_runs`, `agent_learning_memories`, and `strategy_skills` in that order.

- [ ] **Step 5: Add repository tests**

Create `tests/integration/test_agent_intelligence_repositories.py` with these tests:

- `test_strategy_skill_repository_seeds_and_lists_ma_cross`: create an in-memory engine, call `create_all(engine)`, call `StrategySkillRepository(session).ensure_seeded(now)`, then assert `get_active("ma_cross")` returns version `1.0.0`, status `active`, and `list_active()` includes exactly one `ma_cross` row.
- `test_learning_memory_repository_creates_reuses_and_retires_active_memory`: call `get_or_create_active()` twice with identical `(memory_type, source_type, source_id, reason_code)` and assert the same row id is returned, then retire it and assert a new active row can be created for the same source tuple.
- `test_learning_memory_repository_retrieves_symbol_and_skill_scoped_memories_first`: create global, symbol-specific, and strategy-skill memories, then assert `list_active(symbol="000001", strategy_skill_id=skill.id, limit=10)` orders exact symbol/skill matches before global memories and excludes retired/expired rows.
- `test_review_board_repositories_record_run_and_votes`: create a running board run, record votes for all five reviewer roles, mark the run completed, then assert `list_recent()` returns the completed run with `final_recommendation="needs_more_research"` and `list_for_board()` returns the five persisted votes.

- [ ] **Step 6: Implement repositories**

Add repository classes to `src/quant_trading/storage/repositories.py` with these concrete public signatures:

```text
StrategySkillRepository.__init__(session: Session) -> None
StrategySkillRepository.ensure_seeded(now: datetime) -> StrategySkillORM
StrategySkillRepository.get_active(skill_key: str) -> StrategySkillORM | None
StrategySkillRepository.list_active(limit: int = 50) -> list[StrategySkillORM]

AgentLearningMemoryRepository.__init__(session: Session) -> None
AgentLearningMemoryRepository.get(memory_id: int) -> AgentLearningMemoryORM | None
AgentLearningMemoryRepository.get_or_create_active(memory_type: str, scope: str, source_type: str, source_id: int, reason_code: str, title: str, content: str, evidence_payload: dict, confidence: Decimal, importance: Decimal, now: datetime, symbol: str | None = None, strategy_skill_id: int | None = None, expires_at: datetime | None = None, created_by: str = "system") -> tuple[AgentLearningMemoryORM, bool]
AgentLearningMemoryRepository.list_active(symbol: str | None = None, strategy_skill_id: int | None = None, memory_types: list[str] | None = None, limit: int = 50, now: datetime | None = None) -> list[AgentLearningMemoryORM]
AgentLearningMemoryRepository.retire(memory_id: int, retired_by: str, retired_reason: str, now: datetime) -> AgentLearningMemoryORM

AgentReviewBoardRunRepository.__init__(session: Session) -> None
AgentReviewBoardRunRepository.create_running(subject_type: str, subject_id: int, memory_ids: list[int], now: datetime) -> AgentReviewBoardRunORM
AgentReviewBoardRunRepository.mark_completed(board_run_id: int, final_recommendation: str, blocking_reason_codes: list[str], summary_payload: dict, finished_at: datetime, duration_ms: int) -> AgentReviewBoardRunORM
AgentReviewBoardRunRepository.mark_failed(board_run_id: int, error_message: str, finished_at: datetime, duration_ms: int) -> AgentReviewBoardRunORM
AgentReviewBoardRunRepository.list_recent(limit: int = 50) -> list[AgentReviewBoardRunORM]
AgentReviewBoardRunRepository.get(run_id: int) -> AgentReviewBoardRunORM | None

AgentReviewBoardVoteRepository.__init__(session: Session) -> None
AgentReviewBoardVoteRepository.record(board_run_id: int, reviewer_role: str, vote: str, reason_code: str, rationale: str, evidence_payload: dict, now: datetime, agent_run_id: int | None = None) -> AgentReviewBoardVoteORM
AgentReviewBoardVoteRepository.list_for_board(board_run_id: int) -> list[AgentReviewBoardVoteORM]
```

Use existing helpers `_cap_text()` and `_ops_json_dumps()` for text and JSON caps. If a new JSON helper is needed, add `_agent_json_dumps(payload: dict | list) -> str` that uses `ensure_ascii=False`, `sort_keys=True`, and `default=str`.

- [ ] **Step 7: Verify storage layer**

Run:

```bash
pytest tests/integration/test_migrations.py tests/integration/test_agent_intelligence_repositories.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260706_0011_add_agent_memory_skill_review_board.py tests/integration/test_migrations.py tests/integration/test_agent_intelligence_repositories.py
git commit -m "feat: add agent intelligence storage"
```

## Task 2: Strategy Skill Registry And Candidate Validation

**Files:**
- Create: `src/quant_trading/agents/skills.py`
- Modify: `src/quant_trading/agents/candidates.py`
- Modify: `src/quant_trading/agents/service.py`
- Create: `tests/unit/test_strategy_skill_registry.py`
- Modify: `tests/integration/test_agents_jobs.py`

- [ ] **Step 1: Write failing unit tests for skill registry**

Create `tests/unit/test_strategy_skill_registry.py`:

```python
from decimal import Decimal

from quant_trading.agents.skills import StrategySkillRegistry, default_ma_cross_skill


def test_default_ma_cross_skill_payload_matches_seed_contract():
    skill = default_ma_cross_skill()
    assert skill.skill_key == "ma_cross"
    assert skill.version == "1.0.0"
    assert skill.status == "active"
    assert "short_window" in skill.parameter_schema
    assert "long_window" in skill.parameter_schema


def test_registry_validates_ma_cross_candidate_and_preserves_backtest_payload():
    registry = StrategySkillRegistry.from_defaults()
    result = registry.validate_candidate(
        {
            "strategy_skill_key": "ma_cross",
            "strategy_skill_version": "1.0.0",
            "thesis": "Research a moving-average crossover regime.",
            "market_regime_assumption": "Trending market.",
            "entry_rules": {"short_window": 5, "long_window": 20},
            "exit_rules": {"short_window": 5, "long_window": 20},
            "risk_controls": ["max order size"],
            "parameters_to_test": {"short_window": 5, "long_window": 20, "order_size": 100, "initial_cash": "100000"},
            "data_requirements": ["daily OHLCV"],
            "failure_modes": ["sideways whipsaw"],
            "backtest_readiness": "ready",
        },
        request_symbol="000001",
    )

    assert result.validation_status == "passed"
    assert result.candidate_payload["strategy_name"] == "ma_cross"
    assert result.candidate_payload["strategy_skill_key"] == "ma_cross"
    assert result.backtest_request_payload["job_type"] == "backtest_ma_cross"
    assert result.backtest_request_payload["payload"]["initial_cash"] == "100000"


def test_registry_rejects_unsupported_skill_without_backtest_payload():
    registry = StrategySkillRegistry.from_defaults()
    result = registry.validate_candidate(
        {"strategy_skill_key": "arbitrary_python", "thesis": "run generated code"},
        request_symbol="000001",
    )

    assert result.validation_status == "failed"
    assert "unsupported strategy_skill_key: arbitrary_python" in result.validation_errors
    assert result.backtest_request_payload is None
```

- [ ] **Step 2: Run skill registry tests to verify they fail**

Run:

```bash
pytest tests/unit/test_strategy_skill_registry.py -q
```

Expected: FAIL because `quant_trading.agents.skills` does not exist.

- [ ] **Step 3: Implement `src/quant_trading/agents/skills.py`**

Create dataclasses and registry:

```python
@dataclass(frozen=True)
class StrategySkillPayload:
    skill_key: str
    version: str
    display_name: str
    status: str
    parameter_schema: dict[str, Any]
    prompt_guidance: str


@dataclass(frozen=True)
class SkillValidationResult:
    validation_status: str
    validation_errors: list[str]
    safety_flags: list[str]
    candidate_payload: dict[str, Any] | None
    backtest_request_payload: dict[str, Any] | None
    requires_human_approval: bool = True


class StrategySkillRegistry:
    @classmethod
    def from_defaults(cls) -> StrategySkillRegistry:
        return cls([default_ma_cross_skill()])

    @classmethod
    def from_repository(cls, repository: StrategySkillRepository) -> StrategySkillRegistry:
        return cls([skill_payload_from_orm(row) for row in repository.list_active(limit=50)])

    def get_active(self, skill_key: str) -> StrategySkillPayload | None:
        return self._skills_by_key.get(skill_key)

    def list_active(self) -> list[StrategySkillPayload]:
        return list(self._skills_by_key.values())

    def validate_candidate(self, payload: dict[str, Any], *, request_symbol: str | None) -> SkillValidationResult:
        skill_key = str(payload.get("strategy_skill_key") or payload.get("strategy_template") or payload.get("strategy_name") or "ma_cross")
        skill = self.get_active(skill_key)
        if skill is None:
            return SkillValidationResult("failed", [f"unsupported strategy_skill_key: {skill_key}"], [], None, None)
        return validate_ma_cross_candidate(payload, request_symbol=request_symbol, skill=skill)
```

For V1, `validate_candidate()` must support only `ma_cross`. Move reusable parsing from `agents/candidates.py` into this module or call private helpers only after making them local to this module. Do not add arbitrary strategy support.

- [ ] **Step 4: Preserve `validate_strategy_candidate()` response shape**

Modify `src/quant_trading/agents/candidates.py` so this call still works:

```python
result = validate_strategy_candidate(parsed_payload, request_symbol="000001")
```

It must return a dict with:

```python
{
    "validation_status": "passed",
    "validation_errors": [],
    "safety_flags": [],
    "candidate_payload": {
        "strategy_name": "ma_cross",
        "symbol": "000001",
        "parameters": {"short_window": 5, "long_window": 20, "order_size": 100},
        "requires_human_approval": True,
    },
    "backtest_request_payload": {
        "job_type": "backtest_ma_cross",
        "payload": {
            "symbol": "000001",
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
            "initial_cash": "100000",
        },
    },
    "requires_human_approval": True,
}
```

When validation passes, `candidate_payload` must include optional new fields:

```python
"strategy_skill_key": "ma_cross",
"strategy_skill_version": "1.0.0",
```

Existing tests that only check `strategy_name`, `symbol`, and `parameters` must continue to pass.

- [ ] **Step 5: Wire registry into strategy idea service**

In `run_strategy_idea_agent()` in `src/quant_trading/agents/service.py`, validate parsed payload using a repository-backed registry:

```python
with session_scope(engine) as session:
    skill_repo = StrategySkillRepository(session)
    skill_repo.ensure_seeded(_utcnow())
    registry = StrategySkillRegistry.from_repository(skill_repo)
    validation_payload = registry.validate_candidate(
        parsed_payload["spec"],
        request_symbol=clean_request.symbol,
    ).to_result_payload()
```

If this exact placement makes transaction handling awkward, use a small helper `_validate_strategy_candidate_with_registry(engine, parsed_payload, clean_request)` in `service.py`.

- [ ] **Step 6: Add integration regression**

In `tests/integration/test_agents_jobs.py`, add a regression asserting a successful `strategy_idea` result still includes `candidate_payload`, `backtest_request_payload`, `requires_human_approval=True`, and now includes `strategy_skill_key="ma_cross"`.

- [ ] **Step 7: Verify Task 2**

Run:

```bash
pytest tests/unit/test_strategy_skill_registry.py tests/integration/test_agents_jobs.py tests/unit/test_backtest_review_agent.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/quant_trading/agents/skills.py src/quant_trading/agents/candidates.py src/quant_trading/agents/service.py tests/unit/test_strategy_skill_registry.py tests/integration/test_agents_jobs.py
git commit -m "feat: add strategy skill registry"
```

## Task 3: Shared Output Safety And Learning Memory Service

**Files:**
- Create: `src/quant_trading/agents/output_safety.py`
- Modify: `src/quant_trading/agents/backtest_review.py`
- Create: `src/quant_trading/agents/memory.py`
- Create: `tests/unit/test_agent_learning_memory.py`
- Modify: `tests/unit/test_backtest_review_agent.py`

- [ ] **Step 1: Extract unsafe output scanner tests**

In `tests/unit/test_agent_learning_memory.py`, start with:

```python
from quant_trading.agents.output_safety import contains_unsafe_agent_text


def test_shared_output_safety_rejects_live_order_and_code_text():
    assert contains_unsafe_agent_text(["place a live order tomorrow"]) is True
    assert contains_unsafe_agent_text(["```python\nprint('trade')\n```"]) is True
    assert contains_unsafe_agent_text(["research-only validation summary"]) is False
```

- [ ] **Step 2: Run scanner test to verify it fails**

Run:

```bash
pytest tests/unit/test_agent_learning_memory.py::test_shared_output_safety_rejects_live_order_and_code_text -q
```

Expected: FAIL because `output_safety.py` does not exist.

- [ ] **Step 3: Create shared scanner**

Create `src/quant_trading/agents/output_safety.py` with:

```python
UNSAFE_AGENT_TEXT_PATTERNS = (
    re.compile(r"\b(?:submit|place|send|create|execute)\b.{0,40}\b(?:order|orders|trade|trades|trading)\b", re.IGNORECASE),
    re.compile(r"\b(?:live\s+trading|go\s+live|real\s+money|production\s+trading)\b", re.IGNORECASE),
    re.compile(r"\b(?:guarantee|guaranteed|risk-free)\b.{0,40}\b(?:profit|return|gain)", re.IGNORECASE),
    re.compile(r"```", re.IGNORECASE),
    re.compile(r"\bdef\s+\w+\s*\(", re.IGNORECASE),
    re.compile(r"\bclass\s+\w+\s*[:(]", re.IGNORECASE),
    re.compile(r"\bimport\s+[\w.]+", re.IGNORECASE),
    re.compile(r"真实下单|实盘交易|保证收益|稳赚", re.IGNORECASE),
)


def contains_unsafe_agent_text(values: list[str]) -> bool:
    return any(
        pattern.search(str(value or ""))
        for value in values
        for pattern in UNSAFE_AGENT_TEXT_PATTERNS
    )
```

- [ ] **Step 4: Wire backtest review to shared scanner**

Modify `src/quant_trading/agents/backtest_review.py`:

```python
from quant_trading.agents.output_safety import contains_unsafe_agent_text
```

Then replace existing `_contains_unsafe_text()` calls that pass review text lists with `contains_unsafe_agent_text()`. Leave compatibility tests in `tests/unit/test_backtest_review_agent.py` unchanged except for import adjustments if needed.

- [ ] **Step 5: Add failing memory service tests**

Add these tests to `tests/unit/test_agent_learning_memory.py`:

```python
def test_memory_service_rejects_unsafe_memory_text(in_memory_engine):
    service = LearningMemoryService(in_memory_engine)
    with pytest.raises(LearningMemoryError, match="unsafe memory content"):
        service.create_manual_memory(
            memory_type="operator_decision",
            scope="global",
            title="bad",
            content="place a live order tomorrow",
            reason_code="unsafe",
            operator="tester",
        )


def test_memory_service_extracts_operator_rejection_memory(in_memory_engine, rejected_candidate_review):
    service = LearningMemoryService(in_memory_engine)
    results = service.extract_from_candidate_review(rejected_candidate_review.id)
    assert len(results) == 1
    assert results[0].memory_type == "operator_decision"
    assert results[0].reason_code == "candidate_rejected"
```

Use local pytest fixtures that create an in-memory engine, call `create_all(engine)`, and insert a rejected `AgentCandidateReviewORM` row.

- [ ] **Step 6: Run memory tests to verify they fail**

Run:

```bash
pytest tests/unit/test_agent_learning_memory.py -q
```

Expected: FAIL because `LearningMemoryService` is not implemented.

- [ ] **Step 7: Implement `LearningMemoryService`**

Create `src/quant_trading/agents/memory.py` with:

```python
class LearningMemoryError(ValueError):
    pass


class LearningMemoryNotFoundError(LearningMemoryError):
    pass


@dataclass(frozen=True)
class MemoryPayload:
    id: int
    memory_type: str
    scope: str
    symbol: str | None
    strategy_skill_id: int | None
    title: str
    content: str
    reason_code: str
    confidence: Decimal
    importance: Decimal
    source_type: str
    source_id: int


class LearningMemoryService:
    def __init__(self, engine: Engine):
        self.engine = engine
```

Implementation details:

- Public signatures:
  - `create_manual_memory(memory_type: str, scope: str, title: str, content: str, reason_code: str, operator: str, symbol: str | None = None, strategy_skill_id: int | None = None, source_type: str = "operator_approval_request", source_id: int = 0, evidence_payload: dict[str, Any] | None = None, confidence: Decimal = Decimal("1"), importance: Decimal = Decimal("0.5"), expires_at: datetime | None = None) -> MemoryPayload`
  - `extract_from_candidate_review(candidate_review_id: int) -> list[MemoryPayload]`
  - `extract_from_validation_report(report_id: int) -> list[MemoryPayload]`
  - `extract_from_safety_incident(incident_id: int) -> list[MemoryPayload]`
  - `retrieve(symbol: str | None = None, strategy_skill_id: int | None = None, memory_types: list[str] | None = None, limit: int = 8, max_chars: int = 3000) -> list[MemoryPayload]`
  - `retire(memory_id: int, operator: str, reason: str) -> MemoryPayload`
- Cap `title` to 160 characters and `content` to 4000 characters.
- Reject unsafe content using `contains_unsafe_agent_text([title, content])`.
- Use `AgentLearningMemoryRepository.get_or_create_active()` for idempotency.
- Rejected candidate reviews create `memory_type="operator_decision"`, `reason_code="candidate_rejected"`, `importance=0.8`, `confidence=1.0`.
- Failed validation reports create `memory_type="strategy_failure"`, `reason_code` from the first summary reason code or `"research_validation_failed"`, `importance=0.7`, `confidence=0.9`.
- Passed validation reports create `memory_type="strategy_success"`, `reason_code="research_validation_passed"`, `importance=0.5`, `confidence=0.7`.

- [ ] **Step 8: Verify Task 3**

Run:

```bash
pytest tests/unit/test_agent_learning_memory.py tests/unit/test_backtest_review_agent.py tests/integration/test_agent_intelligence_repositories.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add src/quant_trading/agents/output_safety.py src/quant_trading/agents/backtest_review.py src/quant_trading/agents/memory.py tests/unit/test_agent_learning_memory.py tests/unit/test_backtest_review_agent.py
git commit -m "feat: add agent learning memory service"
```

## Task 4: Review Board Service And Coordinator

**Files:**
- Create: `src/quant_trading/agents/review_board.py`
- Create: `tests/unit/test_agent_review_board.py`
- Create: `tests/integration/test_agent_review_board_service.py`

- [ ] **Step 1: Write failing coordinator unit tests**

Create `tests/unit/test_agent_review_board.py`:

```python
from quant_trading.agents.review_board import (
    ReviewBoardVote,
    coordinator_recommendation,
    parse_reviewer_vote,
)


def test_parse_reviewer_vote_falls_back_to_needs_review_on_invalid_json():
    vote = parse_reviewer_vote("not json", reviewer_role="risk_officer")
    assert vote.vote == "needs_review"
    assert vote.reason_code == "invalid_reviewer_output"


def test_coordinator_caps_not_ready_floor_to_needs_more_research():
    result = coordinator_recommendation(
        votes=[ReviewBoardVote("validation_reviewer", "pass", "ok", "looks fine", {})],
        readiness_floor="not_ready",
        data_quality_status="passed",
    )
    assert result.final_recommendation == "needs_more_research"


def test_coordinator_rejects_failed_data_quality():
    result = coordinator_recommendation(
        votes=[ReviewBoardVote("strategy_researcher", "pass", "ok", "clear", {})],
        readiness_floor="ready_for_paper_research",
        data_quality_status="failed",
    )
    assert result.final_recommendation == "reject"
    assert "data_quality_failed" in result.blocking_reason_codes
```

- [ ] **Step 2: Run unit tests to verify they fail**

Run:

```bash
pytest tests/unit/test_agent_review_board.py -q
```

Expected: FAIL because `review_board.py` does not exist.

- [ ] **Step 3: Implement review board core types**

Create `src/quant_trading/agents/review_board.py` with:

```python
@dataclass(frozen=True)
class ReviewBoardVote:
    reviewer_role: str
    vote: str
    reason_code: str
    rationale: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class CoordinatorRecommendation:
    final_recommendation: str
    blocking_reason_codes: list[str]
    summary: dict[str, Any]
```

Implement:

```text
parse_reviewer_vote(content: str, reviewer_role: str) -> ReviewBoardVote
coordinator_recommendation(votes: list[ReviewBoardVote], readiness_floor: str, data_quality_status: str) -> CoordinatorRecommendation
```

Rules:

- Invalid JSON returns `needs_review / invalid_reviewer_output`.
- Unsupported vote returns `needs_review / invalid_reviewer_output`.
- Unsafe text in rationale returns `needs_review / unsafe_reviewer_output`.
- `data_quality_status="failed"` returns `reject`.
- `readiness_floor="not_ready"` returns at most `needs_more_research`.
- Any `vote="block"` returns at most `needs_more_research`.
- All pass with readiness floor `ready_for_paper_research` returns `ready_for_paper_research_consideration`.

- [ ] **Step 4: Write failing service integration test**

Create `tests/integration/test_agent_review_board_service.py`:

```python
def test_review_board_service_persists_deterministic_votes_for_candidate_review():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    candidate_review_id = seed_candidate_review_with_validation_report(
        engine,
        validation_status="needs_review",
        readiness_floor="not_ready",
        data_quality_status="passed",
    )

    result = ReviewBoardService(engine).run_for_candidate_review(candidate_review_id)

    assert result.final_recommendation == "needs_more_research"
    with session_scope(engine) as session:
        board_runs = AgentReviewBoardRunRepository(session).list_recent(limit=10)
        assert len(board_runs) == 1
        votes = AgentReviewBoardVoteRepository(session).list_for_board(board_runs[0].id)
        assert {vote.reviewer_role for vote in votes} == {
            "data_steward",
            "strategy_researcher",
            "risk_officer",
            "validation_reviewer",
            "operations_reviewer",
        }
```

Use helper seed functions in the test file that insert the minimum required `AgentCandidateReviewORM`, `BacktestRunORM`, `DataQualityReportORM`, and `ResearchValidationReportORM` rows.

- [ ] **Step 5: Implement `ReviewBoardService`**

Add:

```text
ReviewBoardService.__init__(engine: Engine) -> None
ReviewBoardService.run_for_candidate_review(candidate_review_id: int) -> CoordinatorRecommendation
```

Implementation:

- Load candidate review and linked validation/data quality reports.
- Retrieve up to 8 active memories using `LearningMemoryService.retrieve()`.
- Create `AgentReviewBoardRunORM`.
- Record five deterministic votes:
  - `data_steward`: block if data quality failed, needs_review if not passed, pass otherwise.
  - `strategy_researcher`: needs_review if strategy skill missing or unsupported, pass otherwise.
  - `risk_officer`: needs_review if validation reasons include drawdown or overfit reason codes, pass otherwise.
  - `validation_reviewer`: block if readiness floor `not_ready`, needs_review if `needs_review`, pass otherwise.
  - `operations_reviewer`: pass for V1 unless unresolved pre-live safety incidents are linked to the candidate subject.
- Persist coordinator recommendation.
- Mark the board run failed with sanitized error on exceptions.

- [ ] **Step 6: Verify Task 4**

Run:

```bash
pytest tests/unit/test_agent_review_board.py tests/integration/test_agent_review_board_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/quant_trading/agents/review_board.py tests/unit/test_agent_review_board.py tests/integration/test_agent_review_board_service.py
git commit -m "feat: add agent review board service"
```

## Task 5: Agent Intelligence API, Dashboard, And README

**Files:**
- Create: `src/quant_trading/api/routes/agent_intelligence.py`
- Modify: `src/quant_trading/api/main.py`
- Modify: `src/quant_trading/api/routes/dashboard.py`
- Create: `tests/integration/test_agent_intelligence_api.py`
- Modify: `tests/integration/test_dashboard.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing API tests**

Create `tests/integration/test_agent_intelligence_api.py`:

```python
def test_agent_intelligence_lists_seeded_skills():
    client, _ = make_client()
    response = client.get("/agents/skills")
    assert response.status_code == 200
    assert response.json()[0]["skill_key"] == "ma_cross"
    assert response.json()[0]["version"] == "1.0.0"


def test_extract_candidate_memories_command_requires_auth_when_enabled():
    client, _ = make_client(require_auth=True, token="secret")
    response = client.post("/agents/candidate-reviews/1/extract-memories")
    assert response.status_code == 401


def test_review_board_command_does_not_create_paper_or_broker_rows():
    client, engine = make_client()
    candidate_review_id = seed_candidate_review_with_validation_report(engine)
    response = client.post(f"/agents/candidate-reviews/{candidate_review_id}/review-board")
    assert response.status_code == 200
    assert response.json()["final_recommendation"] in {
        "reject",
        "needs_more_research",
        "ready_for_human_backtest_approval",
        "ready_for_paper_research_consideration",
    }
    with session_scope(engine) as session:
        assert session.scalar(select(func.count(PaperRunORM.id))) == 0
        assert session.scalar(select(func.count(BrokerOrderEventORM.id))) == 0
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
pytest tests/integration/test_agent_intelligence_api.py -q
```

Expected: FAIL because `agent_intelligence.py` route is not registered.

- [ ] **Step 3: Implement API route**

Create `src/quant_trading/api/routes/agent_intelligence.py` with `router = APIRouter(prefix="/agents", tags=["agent-intelligence"])`.

Endpoints:

```text
GET /agents/skills -> list active strategy skill payloads
GET /agents/skills/{skill_key} -> one active strategy skill or 404
GET /agents/memories?symbol=000001&limit=50 -> active memory payloads
POST /agents/memories/{memory_id}/retire with {"operator": "tester", "reason": "superseded"} -> retired memory payload
GET /agents/review-board-runs?limit=50 -> recent board run payloads
GET /agents/review-board-runs/{run_id} -> board run payload plus vote payloads
POST /agents/candidate-reviews/{candidate_review_id}/extract-memories -> extracted memory payloads
POST /agents/research-validation-reports/{report_id}/extract-memories -> extracted memory payloads
POST /agents/candidate-reviews/{candidate_review_id}/review-board -> coordinator recommendation payload
```

Use existing auth middleware by relying on route registration. Do not add auth bypasses.

- [ ] **Step 4: Register router**

Modify `src/quant_trading/api/main.py`:

```python
from quant_trading.api.routes import agent_intelligence
app.include_router(agent_intelligence.router)
```

Register after `agent_candidates.router` so `/agents/*` routes stay grouped.

- [ ] **Step 5: Add dashboard tests**

Modify `tests/integration/test_dashboard.py`:

```python
def test_dashboard_displays_agent_intelligence_section():
    client, _ = make_client()
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text
    assert "Agent Intelligence" in html
    assert "Active Strategy Skills" in html
    assert "Recent Learning Memories" in html
    assert "Recent Review Board Runs" in html
```

- [ ] **Step 6: Render dashboard section**

Modify `_collect_state()` in `src/quant_trading/api/routes/dashboard.py` to include:

```python
"strategy_skills": StrategySkillRepository(session).list_active(limit=10),
"learning_memories": AgentLearningMemoryRepository(session).list_active(limit=10),
"review_board_runs": AgentReviewBoardRunRepository(session).list_recent(limit=10),
```

Add `_agent_intelligence_section(state)` using existing `_table()` and `_metric()` helpers. Insert it after existing agent/candidate sections and before operations safety if the local layout makes that order clearer.

- [ ] **Step 7: Update README**

Add a section named `Quant Agent Intelligence Layer` describing:

- learning memories are advisory context, not authority;
- `ma_cross` is the only executable backtest skill in V1;
- review board recommendations do not create paper runs, broker calls, or order intents;
- command endpoint examples use localhost and no secrets;
- auth protects command APIs when enabled.

- [ ] **Step 8: Verify Task 5**

Run:

```bash
pytest tests/integration/test_agent_intelligence_api.py tests/integration/test_dashboard.py tests/integration/test_runtime_auth.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 5**

```bash
git add src/quant_trading/api/routes/agent_intelligence.py src/quant_trading/api/main.py src/quant_trading/api/routes/dashboard.py tests/integration/test_agent_intelligence_api.py tests/integration/test_dashboard.py README.md
git commit -m "feat: expose agent intelligence operations"
```

## Task 6: Full Verification, Docs Review, And Final Review

**Files:**
- Modify only if verification exposes a defect.

- [ ] **Step 1: Run storage and service tests**

Run:

```bash
pytest tests/integration/test_migrations.py tests/integration/test_agent_intelligence_repositories.py tests/unit/test_strategy_skill_registry.py tests/unit/test_agent_learning_memory.py tests/unit/test_agent_review_board.py tests/integration/test_agent_review_board_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run API and dashboard tests**

Run:

```bash
pytest tests/integration/test_agent_intelligence_api.py tests/integration/test_dashboard.py tests/integration/test_agents_jobs.py tests/integration/test_agent_candidates_api.py -q
```

Expected: PASS.

- [ ] **Step 3: Run safety regression tests**

Run:

```bash
pytest tests/unit/test_backtest_review_agent.py tests/unit/test_operations_safety.py tests/integration/test_operations_api.py tests/integration/test_paper_engine.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full suite**

Run:

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Run compile and whitespace checks**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m compileall -q src
git diff --check
```

Expected: both commands exit `0`.

- [ ] **Step 6: Final spec review**

Review the implementation against `docs/superpowers/specs/2026-07-06-quant-agent-memory-skill-collaboration-v1-design.md`.

Checklist:

- Four new tables and `ma_cross` seed exist.
- Strategy skill registry preserves `ma_cross` backward compatibility.
- Learning memories are deterministic, source-linked, capped, and unsafe text checked.
- Review board persists five specialist votes and coordinator caps.
- APIs are auth-protected for commands.
- Dashboard uses escaped server-rendered helpers.
- README states no generated code execution, no automatic paper runs, no broker calls, and no live trading.

- [ ] **Step 7: Final quality review**

Review:

- transaction boundaries and idempotency;
- partial unique index behavior;
- JSON payload size caps;
- unsafe scanner false negatives in obvious live/order/code language;
- no secret leakage through memories;
- no scope creep into live execution;
- test assertions cover behavior rather than incidental markup only.

- [ ] **Step 8: Commit final fixes if needed**

If Step 6 or Step 7 finds defects, fix them and commit:

```bash
git add <changed files>
git commit -m "fix: harden agent intelligence layer"
```

If no defects are found, do not create an empty commit.

## Final Handoff

When all tasks pass:

- Report final branch name and HEAD SHA.
- Report all verification commands and results.
- State whether any known non-blocking risks remain.
- Offer finishing options:
  1. Merge back to `main` locally
  2. Push and create a Pull Request
  3. Keep the branch as-is
  4. Discard this work
