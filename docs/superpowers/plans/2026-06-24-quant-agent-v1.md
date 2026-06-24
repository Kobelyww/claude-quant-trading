# Quant Agent v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build audited, job-driven research agents for market analysis and strategy idea structuring without enabling generated-code execution or trading.

**Architecture:** Add a focused `quant_trading.agents` package for LLM boundaries, deterministic analysis, strategy-spec prompting, and service orchestration. Persist every run in `agent_runs`, reuse the existing job runtime and FastAPI auth patterns, and expose read APIs for auditability.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, pytest, existing inline/RQ job runtime, optional `langchain-deepseek` via lazy import.

---

## File Structure

Create:

- `src/quant_trading/agents/__init__.py` exports the public agent service functions and core dataclasses.
- `src/quant_trading/agents/models.py` defines service-layer dataclasses and constants for agent types, statuses, payload caps, and disclaimer text.
- `src/quant_trading/agents/llm.py` defines `LLMClient`, `LLMResponse`, `FakeLLMClient`, and `DeepSeekLLMClient`.
- `src/quant_trading/agents/market_analysis.py` computes deterministic market metrics and builds safe market-analysis prompts.
- `src/quant_trading/agents/strategy_idea.py` builds safe strategy-spec prompts and parses JSON-first LLM output.
- `src/quant_trading/agents/service.py` coordinates persistence, LLM execution, failure handling, and sanitized return payloads.
- `src/quant_trading/api/routes/agents.py` exposes `GET /agent-runs` and `GET /agent-runs/{agent_run_id}`.
- `migrations/versions/20260624_0007_add_agent_runs.py` creates the `agent_runs` table.
- `tests/integration/test_agent_runs_repository.py` covers repository behavior.
- `tests/integration/test_agents_api.py` covers read routes and auth.
- `tests/integration/test_agents_jobs.py` covers job submission and execution.
- `tests/unit/test_agent_llm.py` covers fake and DeepSeek client behavior.
- `tests/unit/test_market_analysis_agent.py` covers metrics, prompts, and safety.
- `tests/unit/test_strategy_idea_agent.py` covers prompt safety and parsing.

Modify:

- `src/quant_trading/storage/models.py` adds `AgentRunORM`.
- `src/quant_trading/storage/repositories.py` adds `AgentRunRepository`.
- `src/quant_trading/config.py` adds DeepSeek and agent cap settings.
- `src/quant_trading/jobs/runtime.py` adds agent job types and execution routing.
- `src/quant_trading/api/routes/jobs.py` adds agent job submission endpoints.
- `src/quant_trading/api/main.py` registers the agent read routes.
- `tests/integration/test_migrations.py` asserts the new table exists.
- `tests/integration/test_runtime_auth.py` asserts agent routes are protected.
- `tests/unit/test_settings.py` covers new settings and secret redaction.
- `README.md` documents Quant Agent v1.

---

### Task 1: Settings And Agent Dataclasses

**Files:**
- Create: `src/quant_trading/agents/__init__.py`
- Create: `src/quant_trading/agents/models.py`
- Modify: `src/quant_trading/config.py`
- Test: `tests/unit/test_settings.py`

- [ ] **Step 1: Add failing settings tests**

Append to `tests/unit/test_settings.py`:

```python
def test_settings_default_agent_configuration(monkeypatch):
    for key in (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_BASE",
        "DEEPSEEK_MODEL",
        "QUANT_AGENT_PROMPT_MAX_CHARS",
        "QUANT_AGENT_RESULT_MAX_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = AppSettings()

    assert settings.deepseek_api_key is None
    assert settings.deepseek_api_base == "https://api.deepseek.com"
    assert settings.deepseek_model == "deepseek-v4-pro"
    assert settings.agent_prompt_max_chars == 8000
    assert settings.agent_result_max_chars == 12000


def test_settings_accept_agent_configuration():
    settings = AppSettings(
        deepseek_api_key=" secret ",
        deepseek_api_base=" https://example.invalid ",
        deepseek_model=" custom-model ",
        agent_prompt_max_chars=4096,
        agent_result_max_chars=9000,
    )

    assert settings.deepseek_api_key == "secret"
    assert settings.deepseek_api_base == "https://example.invalid"
    assert settings.deepseek_model == "custom-model"
    assert settings.agent_prompt_max_chars == 4096
    assert settings.agent_result_max_chars == 9000


def test_settings_redacts_deepseek_api_key():
    settings = AppSettings(deepseek_api_key="deep-secret")

    rendered = repr(settings)

    assert "deep-secret" not in rendered
    assert "deepseek_api_key" not in rendered
```

- [ ] **Step 2: Run settings tests and verify failure**

Run:

```bash
python -m pytest tests/unit/test_settings.py -q
```

Expected: FAIL because `AppSettings` has no `deepseek_api_key`, `deepseek_api_base`, `deepseek_model`, `agent_prompt_max_chars`, or `agent_result_max_chars`.

- [ ] **Step 3: Add settings fields**

In `src/quant_trading/config.py`, add fields to `AppSettings` after `broker_mode`:

```python
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias="DEEPSEEK_API_KEY",
        repr=False,
    )
    deepseek_api_base: str = Field(
        default="https://api.deepseek.com",
        validation_alias="DEEPSEEK_API_BASE",
    )
    deepseek_model: str = Field(default="deepseek-v4-pro", validation_alias="DEEPSEEK_MODEL")
    agent_prompt_max_chars: int = Field(
        default=8000,
        validation_alias="QUANT_AGENT_PROMPT_MAX_CHARS",
    )
    agent_result_max_chars: int = Field(
        default=12000,
        validation_alias="QUANT_AGENT_RESULT_MAX_CHARS",
    )
```

Update `require_api_token_for_auth()` before `return self`:

```python
        if self.deepseek_api_key is not None:
            self.deepseek_api_key = self.deepseek_api_key.strip() or None
        self.deepseek_api_base = self.deepseek_api_base.strip() or "https://api.deepseek.com"
        self.deepseek_model = self.deepseek_model.strip() or "deepseek-v4-pro"
        if self.agent_prompt_max_chars <= 0:
            raise ValueError("QUANT_AGENT_PROMPT_MAX_CHARS must be positive")
        if self.agent_result_max_chars <= 0:
            raise ValueError("QUANT_AGENT_RESULT_MAX_CHARS must be positive")
```

- [ ] **Step 4: Create agent service dataclasses**

Create `src/quant_trading/agents/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

AGENT_MARKET_ANALYSIS = "market_analysis"
AGENT_STRATEGY_IDEA = "strategy_idea"

STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

REQUEST_VALUE_MAX_CHARS = 4000
MARKET_CONTEXT_MAX_CHARS = 2000
DEFAULT_LOOKBACK_BARS = 252
MIN_LOOKBACK_BARS = 60
MAX_LOOKBACK_BARS = 1000
PROMPT_MAX_CHARS = 8000
RESULT_VALUE_MAX_CHARS = 12000
ERROR_MAX_CHARS = 1000

RESEARCH_DISCLAIMER = (
    "This output is for quantitative research only. It is not investment advice, "
    "does not predict future prices, and must not be used as an instruction to trade."
)


@dataclass(frozen=True)
class MarketAnalysisRequest:
    symbol: str
    start: date | None = None
    end: date | None = None
    lookback_bars: int = DEFAULT_LOOKBACK_BARS
    mode: str = "overview"


@dataclass(frozen=True)
class StrategyIdeaRequest:
    idea: str
    symbol: str | None = None
    market_context: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    agent_type: str
    model_name: str
    request_payload: dict[str, Any]
    metrics_payload: dict[str, Any]
    result_payload: dict[str, Any]
```

Create `src/quant_trading/agents/__init__.py`:

```python
from quant_trading.agents.models import (
    AGENT_MARKET_ANALYSIS,
    AGENT_STRATEGY_IDEA,
    AgentResult,
    MarketAnalysisRequest,
    StrategyIdeaRequest,
)

__all__ = [
    "AGENT_MARKET_ANALYSIS",
    "AGENT_STRATEGY_IDEA",
    "AgentResult",
    "MarketAnalysisRequest",
    "StrategyIdeaRequest",
]
```

- [ ] **Step 5: Run settings tests and verify pass**

Run:

```bash
python -m pytest tests/unit/test_settings.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit settings and dataclasses**

Run:

```bash
git add src/quant_trading/config.py src/quant_trading/agents/__init__.py src/quant_trading/agents/models.py tests/unit/test_settings.py
git commit -m "feat: add quant agent settings"
```

---

### Task 2: Agent Run Schema And Repository

**Files:**
- Modify: `src/quant_trading/storage/models.py`
- Modify: `src/quant_trading/storage/repositories.py`
- Create: `migrations/versions/20260624_0007_add_agent_runs.py`
- Create: `tests/integration/test_agent_runs_repository.py`
- Modify: `tests/integration/test_migrations.py`

- [ ] **Step 1: Add failing repository tests**

Create `tests/integration/test_agent_runs_repository.py`:

```python
import json
from datetime import datetime

from sqlalchemy import select

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import AgentRunORM
from quant_trading.storage.repositories import AgentRunRepository


def make_memory_engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_agent_run_repository_creates_succeeds_lists_and_gets_run():
    engine = make_memory_engine()
    started = datetime(2026, 6, 24, 9, 0, 0)
    finished = datetime(2026, 6, 24, 9, 0, 1)

    with session_scope(engine) as session:
        repo = AgentRunRepository(session)
        row = repo.create_running(
            agent_type="market_analysis",
            symbol="000001",
            model_name="fake-model",
            request_payload='{"symbol":"000001"}',
            job_run_id=7,
            started_at=started,
        )
        repo.mark_succeeded(
            row,
            metrics_payload='{"bar_count":121}',
            result_payload='{"research_only":true}',
            finished_at=finished,
            duration_ms=1000,
        )
        run_id = row.id

    with session_scope(engine) as session:
        repo = AgentRunRepository(session)
        loaded = repo.get(run_id)
        rows = repo.list_recent(agent_type="market_analysis", status="succeeded", symbol="000001")

    assert loaded is not None
    assert loaded.status == "succeeded"
    assert loaded.error_message is None
    assert loaded.job_run_id == 7
    assert json.loads(loaded.metrics_payload) == {"bar_count": 121}
    assert [row.id for row in rows] == [run_id]


def test_agent_run_repository_marks_failed_with_capped_error():
    engine = make_memory_engine()
    started = datetime(2026, 6, 24, 9, 0, 0)
    finished = datetime(2026, 6, 24, 9, 0, 1)

    with session_scope(engine) as session:
        repo = AgentRunRepository(session)
        row = repo.create_running(
            agent_type="strategy_idea",
            symbol=None,
            model_name="fake-model",
            request_payload='{"idea":"x"}',
            job_run_id=None,
            started_at=started,
        )
        repo.mark_failed(row, "x" * 1200, finished_at=finished, duration_ms=1000)
        run_id = row.id

    with session_scope(engine) as session:
        row = session.scalar(select(AgentRunORM).where(AgentRunORM.id == run_id))

    assert row is not None
    assert row.status == "failed"
    assert len(row.error_message) == 1000
```

- [ ] **Step 2: Add failing migration assertion**

In `tests/integration/test_migrations.py`, add:

```python
    assert "agent_runs" in tables
```

After the table assertions, add:

```python
    agent_run_columns = {column["name"] for column in inspector.get_columns("agent_runs")}
    assert {
        "id",
        "agent_type",
        "status",
        "symbol",
        "model_name",
        "request_payload",
        "metrics_payload",
        "result_payload",
        "error_message",
        "job_run_id",
        "started_at",
        "finished_at",
        "duration_ms",
        "created_at",
    } <= agent_run_columns
```

- [ ] **Step 3: Run repository and migration tests and verify failure**

Run:

```bash
python -m pytest tests/integration/test_agent_runs_repository.py tests/integration/test_migrations.py -q
```

Expected: FAIL because `AgentRunORM`, `AgentRunRepository`, and the migration do not exist.

- [ ] **Step 4: Add `AgentRunORM`**

In `src/quant_trading/storage/models.py`, after `DataSyncRunORM`, add:

```python
class AgentRunORM(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    model_name: Mapped[str] = mapped_column(String(128), default="")
    request_payload: Mapped[str] = mapped_column(Text, default="{}")
    metrics_payload: Mapped[str] = mapped_column(Text, default="{}")
    result_payload: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_runs.id"),
        nullable=True,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 5: Add `AgentRunRepository`**

In `src/quant_trading/storage/repositories.py`, add `AgentRunORM` to the import list from `quant_trading.storage.models`.

At the end of `src/quant_trading/storage/repositories.py`, add:

```python
class AgentRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_running(
        self,
        *,
        agent_type: str,
        symbol: str | None,
        model_name: str,
        request_payload: str,
        job_run_id: int | None,
        started_at: datetime,
    ) -> AgentRunORM:
        row = AgentRunORM(
            agent_type=agent_type,
            status="running",
            symbol=symbol,
            model_name=model_name,
            request_payload=request_payload,
            metrics_payload="{}",
            result_payload="{}",
            error_message=None,
            job_run_id=job_run_id,
            started_at=started_at,
            created_at=started_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_succeeded(
        self,
        row: AgentRunORM,
        *,
        metrics_payload: str,
        result_payload: str,
        finished_at: datetime,
        duration_ms: int,
    ) -> AgentRunORM:
        row.status = "succeeded"
        row.metrics_payload = metrics_payload
        row.result_payload = result_payload
        row.error_message = None
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def mark_failed(
        self,
        row: AgentRunORM,
        error_message: str,
        *,
        finished_at: datetime,
        duration_ms: int,
    ) -> AgentRunORM:
        row.status = "failed"
        row.error_message = error_message[:1000]
        row.finished_at = finished_at
        row.duration_ms = duration_ms
        self.session.flush()
        return row

    def list_recent(
        self,
        *,
        agent_type: str | None = None,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[AgentRunORM]:
        statement = select(AgentRunORM).order_by(AgentRunORM.id.desc()).limit(limit)
        if agent_type:
            statement = statement.where(AgentRunORM.agent_type == agent_type)
        if status:
            statement = statement.where(AgentRunORM.status == status)
        if symbol:
            statement = statement.where(AgentRunORM.symbol == symbol)
        return list(self.session.scalars(statement).all())

    def get(self, agent_run_id: int) -> AgentRunORM | None:
        return self.session.get(AgentRunORM, agent_run_id)
```

- [ ] **Step 6: Add migration**

Create `migrations/versions/20260624_0007_add_agent_runs.py`:

```python
"""add agent runs

Revision ID: 20260624_0007
Revises: 20260623_0006
Create Date: 2026-06-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260624_0007"
down_revision = "20260623_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("request_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("metrics_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("job_run_id", sa.Integer(), sa.ForeignKey("job_runs.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_runs_agent_type", "agent_runs", ["agent_type"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_symbol", "agent_runs", ["symbol"])
    op.create_index("ix_agent_runs_job_run_id", "agent_runs", ["job_run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_job_run_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_symbol", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_type", table_name="agent_runs")
    op.drop_table("agent_runs")
```

- [ ] **Step 7: Run repository and migration tests and verify pass**

Run:

```bash
python -m pytest tests/integration/test_agent_runs_repository.py tests/integration/test_migrations.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit schema and repository**

Run:

```bash
git add src/quant_trading/storage/models.py src/quant_trading/storage/repositories.py migrations/versions/20260624_0007_add_agent_runs.py tests/integration/test_agent_runs_repository.py tests/integration/test_migrations.py
git commit -m "feat: add agent run storage"
```

---

### Task 3: LLM Client Boundary

**Files:**
- Create: `src/quant_trading/agents/llm.py`
- Create: `tests/unit/test_agent_llm.py`

- [ ] **Step 1: Add failing LLM boundary tests**

Create `tests/unit/test_agent_llm.py`:

```python
import pytest

from quant_trading.agents.llm import DeepSeekLLMClient, FakeLLMClient, LLMResponse
from quant_trading.config import AppSettings


def test_fake_llm_client_returns_deterministic_response_and_records_prompt():
    client = FakeLLMClient("hello")

    response = client.complete("prompt text")

    assert response == LLMResponse(content="hello", model="fake-llm")
    assert client.prompts == ["prompt text"]


def test_deepseek_client_requires_api_key():
    with pytest.raises(ValueError) as exc_info:
        DeepSeekLLMClient.from_settings(AppSettings(deepseek_api_key=None))

    assert "DEEPSEEK_API_KEY is required for agent jobs" in str(exc_info.value)


def test_deepseek_client_import_error_is_clear(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "langchain_deepseek":
            raise ImportError("missing package")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    client = DeepSeekLLMClient.from_settings(AppSettings(deepseek_api_key="key"))

    with pytest.raises(RuntimeError) as exc_info:
        client.complete("prompt")

    assert "Install langchain-deepseek to use agent jobs" in str(exc_info.value)
```

- [ ] **Step 2: Run LLM tests and verify failure**

Run:

```bash
python -m pytest tests/unit/test_agent_llm.py -q
```

Expected: FAIL because `quant_trading.agents.llm` does not exist.

- [ ] **Step 3: Implement LLM boundary**

Create `src/quant_trading/agents/llm.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from quant_trading.config import AppSettings


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient(Protocol):
    def complete(self, prompt: str) -> LLMResponse:
        raise NotImplementedError


class FakeLLMClient:
    def __init__(self, content: str, model: str = "fake-llm"):
        self.content = content
        self.model = model
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> LLMResponse:
        self.prompts.append(prompt)
        return LLMResponse(content=self.content, model=self.model)


@dataclass(frozen=True)
class DeepSeekLLMClient:
    api_key: str
    api_base: str
    model: str

    @classmethod
    def from_settings(cls, settings: AppSettings) -> "DeepSeekLLMClient":
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for agent jobs")
        return cls(
            api_key=settings.deepseek_api_key,
            api_base=settings.deepseek_api_base,
            model=settings.deepseek_model,
        )

    def complete(self, prompt: str) -> LLMResponse:
        try:
            from langchain_deepseek import ChatDeepSeek
        except ImportError as exc:
            raise RuntimeError("Install langchain-deepseek to use agent jobs") from exc

        llm = ChatDeepSeek(
            model=self.model,
            api_key=self.api_key,
            api_base=self.api_base,
        )
        response = llm.invoke(prompt)
        return LLMResponse(content=str(response.content), model=self.model)
```

- [ ] **Step 4: Run LLM tests and verify pass**

Run:

```bash
python -m pytest tests/unit/test_agent_llm.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit LLM boundary**

Run:

```bash
git add src/quant_trading/agents/llm.py tests/unit/test_agent_llm.py
git commit -m "feat: add quant agent llm boundary"
```

---

### Task 4: Market Analysis Agent

**Files:**
- Create: `src/quant_trading/agents/market_analysis.py`
- Create: `src/quant_trading/agents/service.py`
- Create: `tests/unit/test_market_analysis_agent.py`
- Create: `tests/integration/test_agents_jobs.py`

- [ ] **Step 1: Add failing market-analysis unit tests**

Create `tests/unit/test_market_analysis_agent.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

from quant_trading.agents.llm import FakeLLMClient
from quant_trading.agents.market_analysis import build_market_analysis_prompt, compute_market_metrics
from quant_trading.agents.models import MarketAnalysisRequest
from quant_trading.core.enums import Market
from quant_trading.core.models import Bar


def make_bars(count=121):
    start = date(2026, 1, 1)
    bars = []
    for index in range(count):
        close = Decimal("10") + Decimal(index) / Decimal("10")
        bars.append(
            Bar(
                instrument_id=1,
                symbol="000001",
                market=Market.A_STOCK,
                timestamp=start + timedelta(days=index),
                open=close - Decimal("0.1"),
                high=close + Decimal("0.2"),
                low=close - Decimal("0.2"),
                close=close,
                volume=Decimal("100000") + Decimal(index),
                source="test",
            )
        )
    return bars


def test_compute_market_metrics_from_known_bars():
    metrics = compute_market_metrics(make_bars(), MarketAnalysisRequest(symbol="000001"))

    assert metrics["symbol"] == "000001"
    assert metrics["bar_count"] == 121
    assert metrics["start"] == "2026-01-01"
    assert metrics["end"] == "2026-05-01"
    assert metrics["latest_close"] == "22"
    assert metrics["trend_direction"] == "up"
    assert metrics["volatility_regime"] in {"low", "normal", "high"}
    assert "max_drawdown" in metrics


def test_market_analysis_prompt_contains_safety_constraints():
    metrics = compute_market_metrics(make_bars(), MarketAnalysisRequest(symbol="000001"))

    prompt = build_market_analysis_prompt(metrics, mode="overview", max_chars=8000)

    assert "historical data only" in prompt
    assert "Do not provide buy or sell recommendations" in prompt
    assert "Do not predict future prices" in prompt
    assert "Chinese" in prompt
    assert "000001" in prompt


def test_fake_llm_is_usable_for_market_analysis_prompt():
    llm = FakeLLMClient("研究报告")

    response = llm.complete("prompt")

    assert response.content == "研究报告"
```

- [ ] **Step 2: Run market-analysis unit tests and verify failure**

Run:

```bash
python -m pytest tests/unit/test_market_analysis_agent.py -q
```

Expected: FAIL because `quant_trading.agents.market_analysis` does not exist.

- [ ] **Step 3: Implement market-analysis metrics and prompt**

Create `src/quant_trading/agents/market_analysis.py`:

```python
from __future__ import annotations

from decimal import Decimal
import json

from quant_trading.agents.models import MarketAnalysisRequest
from quant_trading.core.models import Bar


def compute_market_metrics(bars: list[Bar], request: MarketAnalysisRequest) -> dict[str, str | int | None]:
    if not bars:
        raise ValueError(f"no market bars found for symbol: {request.symbol}")
    if len(bars) < 60:
        raise ValueError(f"insufficient bars for market analysis: required=60 actual={len(bars)}")

    selected = bars[-request.lookback_bars :]
    closes = [bar.close for bar in selected]
    volumes = [bar.volume for bar in selected]
    latest = selected[-1]
    returns = [
        (closes[index] / closes[index - 1]) - Decimal("1")
        for index in range(1, len(closes))
        if closes[index - 1] != 0
    ]
    volatility_20d = _stddev(returns[-20:]) if len(returns) >= 20 else Decimal("0")
    ma_20 = _average(closes[-20:]) if len(closes) >= 20 else closes[-1]
    ma_60 = _average(closes[-60:]) if len(closes) >= 60 else closes[0]
    trend = "up" if ma_20 > ma_60 else "down" if ma_20 < ma_60 else "flat"
    max_drawdown = _max_drawdown(closes)
    volatility_regime = "high" if volatility_20d > Decimal("0.03") else "low" if volatility_20d < Decimal("0.01") else "normal"

    return {
        "symbol": request.symbol,
        "mode": request.mode,
        "source": latest.source,
        "start": selected[0].timestamp.isoformat(),
        "end": selected[-1].timestamp.isoformat(),
        "bar_count": len(selected),
        "latest_close": _plain(latest.close),
        "return_1m": _window_return(closes, 21),
        "return_3m": _window_return(closes, 63),
        "volatility_20d": _plain(volatility_20d),
        "trend_direction": trend,
        "ma_20": _plain(ma_20),
        "ma_60": _plain(ma_60),
        "avg_volume_20d": _plain(_average(volumes[-20:])),
        "high_52w": _plain(max(closes[-252:])),
        "low_52w": _plain(min(closes[-252:])),
        "support_level": _plain(min(closes[-20:])),
        "resistance_level": _plain(max(closes[-20:])),
        "max_drawdown": _plain(max_drawdown),
        "volatility_regime": volatility_regime,
    }


def build_market_analysis_prompt(metrics: dict, mode: str, max_chars: int) -> str:
    prompt = f"""
You are a quantitative research analyst.
Write a concise Chinese market analysis report using historical data only.
Do not provide buy or sell recommendations.
Do not predict future prices.
Do not provide price targets or guaranteed return language.
Use confidence qualifiers such as shows, suggests, and indicates.

Mode: {mode}
Metrics:
{json.dumps(metrics, ensure_ascii=False, sort_keys=True)}

Required sections:
1. 市场概况
2. 趋势分析
3. 波动率与成交量
4. 关键价位
5. 风险因素
6. 市场状态分类
""".strip()
    return prompt[:max_chars]


def _average(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _stddev(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    mean = _average(values)
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(len(values))
    return variance.sqrt()


def _window_return(closes: list[Decimal], window: int) -> str | None:
    if len(closes) <= window or closes[-window - 1] == 0:
        return None
    return _plain((closes[-1] / closes[-window - 1]) - Decimal("1"))


def _max_drawdown(closes: list[Decimal]) -> Decimal:
    peak = closes[0]
    worst = Decimal("0")
    for close in closes:
        if close > peak:
            peak = close
        if peak > 0:
            drawdown = (peak - close) / peak
            if drawdown > worst:
                worst = drawdown
    return worst


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")
```

- [ ] **Step 4: Run market-analysis unit tests and verify pass**

Run:

```bash
python -m pytest tests/unit/test_market_analysis_agent.py -q
```

Expected: PASS.

- [ ] **Step 5: Add failing market-analysis service integration test**

Append to `tests/integration/test_agents_jobs.py`:

```python
from pathlib import Path

from sqlalchemy import select

from quant_trading.agents.llm import FakeLLMClient
from quant_trading.agents.models import MarketAnalysisRequest
from quant_trading.agents.service import run_market_analysis_agent
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.migrate_legacy import import_legacy_sqlite
from quant_trading.storage.models import AgentRunORM


def test_run_market_analysis_agent_persists_success(legacy_sqlite_db: Path):
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)

    result = run_market_analysis_agent(
        engine,
        MarketAnalysisRequest(symbol="000001", lookback_bars=60),
        llm_client=FakeLLMClient("市场研究报告"),
        job_run_id=3,
    )

    with session_scope(engine) as session:
        row = session.scalar(select(AgentRunORM).where(AgentRunORM.id == result["agent_run_id"]))

    assert row is not None
    assert row.status == "succeeded"
    assert row.agent_type == "market_analysis"
    assert row.symbol == "000001"
    assert row.job_run_id == 3
    assert result["research_only"] is True
    assert result["report"] == "市场研究报告"
```

- [ ] **Step 6: Run service integration test and verify failure**

Run:

```bash
python -m pytest tests/integration/test_agents_jobs.py::test_run_market_analysis_agent_persists_success -q
```

Expected: FAIL because `quant_trading.agents.service` does not exist.

- [ ] **Step 7: Implement service helper for market analysis**

Create `src/quant_trading/agents/service.py` with market-analysis support:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any
import json
import time

from sqlalchemy import Engine

from quant_trading.agents.llm import DeepSeekLLMClient, LLMClient
from quant_trading.agents.market_analysis import build_market_analysis_prompt, compute_market_metrics
from quant_trading.agents.models import (
    AGENT_MARKET_ANALYSIS,
    ERROR_MAX_CHARS,
    RESEARCH_DISCLAIMER,
    RESULT_VALUE_MAX_CHARS,
    MarketAnalysisRequest,
)
from quant_trading.config import AppSettings
from quant_trading.storage.db import session_scope
from quant_trading.storage.repositories import AgentRunRepository, MarketDataRepository


def run_market_analysis_agent(
    engine: Engine,
    request: MarketAnalysisRequest,
    *,
    llm_client: LLMClient | None = None,
    job_run_id: int | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    settings = settings or AppSettings()
    llm_client = llm_client or DeepSeekLLMClient.from_settings(settings)
    started_at = _utcnow()
    started_counter = time.perf_counter()
    request_payload = _json_dumps(
        {
            "symbol": request.symbol,
            "start": request.start.isoformat() if request.start else None,
            "end": request.end.isoformat() if request.end else None,
            "lookback_bars": request.lookback_bars,
            "mode": request.mode,
        }
    )

    with session_scope(engine) as session:
        row = AgentRunRepository(session).create_running(
            agent_type=AGENT_MARKET_ANALYSIS,
            symbol=request.symbol,
            model_name=getattr(llm_client, "model", "unknown"),
            request_payload=request_payload,
            job_run_id=job_run_id,
            started_at=started_at,
        )
        agent_run_id = row.id

    try:
        with session_scope(engine) as session:
            bars = MarketDataRepository(session).list_bars(request.symbol)
        if request.start:
            bars = [bar for bar in bars if bar.timestamp >= request.start]
        if request.end:
            bars = [bar for bar in bars if bar.timestamp <= request.end]
        metrics = compute_market_metrics(bars, request)
        prompt = build_market_analysis_prompt(metrics, request.mode, settings.agent_prompt_max_chars)
        response = llm_client.complete(prompt)
        result_payload = {
            "agent_run_id": agent_run_id,
            "agent_type": AGENT_MARKET_ANALYSIS,
            "symbol": request.symbol,
            "report": response.content[: settings.agent_result_max_chars],
            "research_only": True,
            "disclaimer": RESEARCH_DISCLAIMER,
        }
        finished_at = _utcnow()
        with session_scope(engine) as session:
            row = AgentRunRepository(session).get(agent_run_id)
            if row is not None:
                AgentRunRepository(session).mark_succeeded(
                    row,
                    metrics_payload=_json_dumps(metrics),
                    result_payload=_json_dumps(result_payload),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
        return result_payload
    except Exception as exc:
        finished_at = _utcnow()
        with session_scope(engine) as session:
            row = AgentRunRepository(session).get(agent_run_id)
            if row is not None:
                AgentRunRepository(session).mark_failed(
                    row,
                    _sanitize_error(exc),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
        raise


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _sanitize_error(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__)[:ERROR_MAX_CHARS]


def _utcnow() -> datetime:
    return datetime.utcnow()


def _duration_ms(started_counter: float) -> int:
    return max(0, int((time.perf_counter() - started_counter) * 1000))
```

- [ ] **Step 8: Run market-analysis service tests and verify pass**

Run:

```bash
python -m pytest tests/unit/test_market_analysis_agent.py tests/integration/test_agents_jobs.py::test_run_market_analysis_agent_persists_success -q
```

Expected: PASS.

- [ ] **Step 9: Commit market-analysis agent**

Run:

```bash
git add src/quant_trading/agents/market_analysis.py src/quant_trading/agents/service.py tests/unit/test_market_analysis_agent.py tests/integration/test_agents_jobs.py
git commit -m "feat: add market analysis agent"
```

---

### Task 5: Strategy Idea Agent

**Files:**
- Create: `src/quant_trading/agents/strategy_idea.py`
- Modify: `src/quant_trading/agents/service.py`
- Create: `tests/unit/test_strategy_idea_agent.py`
- Modify: `tests/integration/test_agents_jobs.py`

- [ ] **Step 1: Add failing strategy-idea unit tests**

Create `tests/unit/test_strategy_idea_agent.py`:

```python
from quant_trading.agents.models import StrategyIdeaRequest
from quant_trading.agents.strategy_idea import build_strategy_idea_prompt, parse_strategy_idea_response


def test_strategy_idea_prompt_contains_safety_constraints():
    prompt = build_strategy_idea_prompt(
        StrategyIdeaRequest(
            idea="Use moving averages to capture trend continuation",
            symbol="000001",
            market_context="A-share daily bars",
            constraints={"long_only": True},
        ),
        max_chars=8000,
    )

    assert "Do not output executable code" in prompt
    assert "Do not provide live trading instructions" in prompt
    assert "Do not claim profitability" in prompt
    assert "JSON object" in prompt
    assert "entry_rules" in prompt


def test_parse_strategy_idea_response_parses_json_object():
    parsed = parse_strategy_idea_response(
        """{"thesis":"trend","entry_rules":["ma cross"],"exit_rules":["reverse"],"risk_controls":["max loss"],"parameters_to_test":["window"],"data_requirements":["daily bars"],"failure_modes":["chop"],"backtest_readiness":"ready"}"""
    )

    assert parsed["parsed"] is True
    assert parsed["spec"]["thesis"] == "trend"
    assert parsed["spec"]["entry_rules"] == ["ma cross"]


def test_parse_strategy_idea_response_falls_back_to_bounded_narrative():
    parsed = parse_strategy_idea_response("plain narrative")

    assert parsed == {"parsed": False, "narrative": "plain narrative"}
```

- [ ] **Step 2: Run strategy-idea unit tests and verify failure**

Run:

```bash
python -m pytest tests/unit/test_strategy_idea_agent.py -q
```

Expected: FAIL because `quant_trading.agents.strategy_idea` does not exist.

- [ ] **Step 3: Implement strategy-idea prompt and parser**

Create `src/quant_trading/agents/strategy_idea.py`:

```python
from __future__ import annotations

import json
from typing import Any

from quant_trading.agents.models import StrategyIdeaRequest


def build_strategy_idea_prompt(request: StrategyIdeaRequest, max_chars: int) -> str:
    payload = {
        "idea": request.idea,
        "symbol": request.symbol,
        "market_context": request.market_context,
        "constraints": request.constraints,
    }
    prompt = f"""
You are a quantitative research assistant.
Convert the user's trading idea into a research-only strategy specification.
Do not output executable code.
Do not provide live trading instructions.
Do not call brokers, exchanges, or order APIs.
Do not claim profitability.
Do not provide buy or sell recommendations.

Return one JSON object with these keys:
thesis, market_regime_assumption, entry_rules, exit_rules, risk_controls,
parameters_to_test, data_requirements, failure_modes, backtest_readiness.

User payload:
{json.dumps(payload, ensure_ascii=False, sort_keys=True)}
""".strip()
    return prompt[:max_chars]


def parse_strategy_idea_response(content: str) -> dict[str, Any]:
    bounded = content.strip()[:12000]
    try:
        parsed = json.loads(bounded)
    except json.JSONDecodeError:
        return {"parsed": False, "narrative": bounded}
    if not isinstance(parsed, dict):
        return {"parsed": False, "narrative": bounded}
    return {"parsed": True, "spec": parsed}
```

- [ ] **Step 4: Run strategy-idea unit tests and verify pass**

Run:

```bash
python -m pytest tests/unit/test_strategy_idea_agent.py -q
```

Expected: PASS.

- [ ] **Step 5: Add failing strategy-idea service integration test**

Append to `tests/integration/test_agents_jobs.py`:

```python
from quant_trading.agents.models import StrategyIdeaRequest
from quant_trading.agents.service import run_strategy_idea_agent


def test_run_strategy_idea_agent_persists_success():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    result = run_strategy_idea_agent(
        engine,
        StrategyIdeaRequest(idea="Buy pullbacks in an uptrend", symbol="000001"),
        llm_client=FakeLLMClient('{"thesis":"trend pullback","entry_rules":["pullback"],"exit_rules":["stop"],"risk_controls":["size"],"parameters_to_test":["lookback"],"data_requirements":["daily bars"],"failure_modes":["range"],"backtest_readiness":"ready"}'),
        job_run_id=4,
    )

    with session_scope(engine) as session:
        row = session.get(AgentRunORM, result["agent_run_id"])

    assert row is not None
    assert row.status == "succeeded"
    assert row.agent_type == "strategy_idea"
    assert row.symbol == "000001"
    assert result["research_only"] is True
    assert result["parsed"] is True
    assert result["spec"]["thesis"] == "trend pullback"
```

- [ ] **Step 6: Run strategy-idea service test and verify failure**

Run:

```bash
python -m pytest tests/integration/test_agents_jobs.py::test_run_strategy_idea_agent_persists_success -q
```

Expected: FAIL because `run_strategy_idea_agent` does not exist.

- [ ] **Step 7: Implement strategy-idea service**

In `src/quant_trading/agents/service.py`, import strategy helpers:

```python
from quant_trading.agents.models import (
    AGENT_MARKET_ANALYSIS,
    AGENT_STRATEGY_IDEA,
    ERROR_MAX_CHARS,
    MARKET_CONTEXT_MAX_CHARS,
    RESEARCH_DISCLAIMER,
    REQUEST_VALUE_MAX_CHARS,
    RESULT_VALUE_MAX_CHARS,
    MarketAnalysisRequest,
    StrategyIdeaRequest,
)
from quant_trading.agents.strategy_idea import build_strategy_idea_prompt, parse_strategy_idea_response
```

Add function:

```python
def run_strategy_idea_agent(
    engine: Engine,
    request: StrategyIdeaRequest,
    *,
    llm_client: LLMClient | None = None,
    job_run_id: int | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    settings = settings or AppSettings()
    llm_client = llm_client or DeepSeekLLMClient.from_settings(settings)
    started_at = _utcnow()
    started_counter = time.perf_counter()
    clean_request = StrategyIdeaRequest(
        idea=request.idea[:REQUEST_VALUE_MAX_CHARS],
        symbol=request.symbol.strip()[:32] if request.symbol else None,
        market_context=request.market_context[:MARKET_CONTEXT_MAX_CHARS] if request.market_context else None,
        constraints=request.constraints,
    )
    request_payload = _json_dumps(
        {
            "idea": clean_request.idea,
            "symbol": clean_request.symbol,
            "market_context": clean_request.market_context,
            "constraints": clean_request.constraints,
        }
    )
    with session_scope(engine) as session:
        row = AgentRunRepository(session).create_running(
            agent_type=AGENT_STRATEGY_IDEA,
            symbol=clean_request.symbol,
            model_name=getattr(llm_client, "model", "unknown"),
            request_payload=request_payload,
            job_run_id=job_run_id,
            started_at=started_at,
        )
        agent_run_id = row.id
    try:
        prompt = build_strategy_idea_prompt(clean_request, settings.agent_prompt_max_chars)
        response = llm_client.complete(prompt)
        parsed_payload = parse_strategy_idea_response(response.content[: settings.agent_result_max_chars])
        result_payload = {
            "agent_run_id": agent_run_id,
            "agent_type": AGENT_STRATEGY_IDEA,
            "symbol": clean_request.symbol,
            "research_only": True,
            "disclaimer": RESEARCH_DISCLAIMER,
            **parsed_payload,
        }
        finished_at = _utcnow()
        with session_scope(engine) as session:
            row = AgentRunRepository(session).get(agent_run_id)
            if row is not None:
                AgentRunRepository(session).mark_succeeded(
                    row,
                    metrics_payload="{}",
                    result_payload=_json_dumps(result_payload),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
        return result_payload
    except Exception as exc:
        finished_at = _utcnow()
        with session_scope(engine) as session:
            row = AgentRunRepository(session).get(agent_run_id)
            if row is not None:
                AgentRunRepository(session).mark_failed(
                    row,
                    _sanitize_error(exc),
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_counter),
                )
        raise
```

- [ ] **Step 8: Export service functions**

Update `src/quant_trading/agents/__init__.py`:

```python
from quant_trading.agents.service import run_market_analysis_agent, run_strategy_idea_agent
```

Add `"run_market_analysis_agent"` and `"run_strategy_idea_agent"` to `__all__`.

- [ ] **Step 9: Run strategy-idea tests and verify pass**

Run:

```bash
python -m pytest tests/unit/test_strategy_idea_agent.py tests/integration/test_agents_jobs.py::test_run_strategy_idea_agent_persists_success -q
```

Expected: PASS.

- [ ] **Step 10: Commit strategy-idea agent**

Run:

```bash
git add src/quant_trading/agents/__init__.py src/quant_trading/agents/strategy_idea.py src/quant_trading/agents/service.py tests/unit/test_strategy_idea_agent.py tests/integration/test_agents_jobs.py
git commit -m "feat: add strategy idea agent"
```

---

### Task 6: Job Runtime And Agent APIs

**Files:**
- Modify: `src/quant_trading/jobs/runtime.py`
- Modify: `src/quant_trading/api/routes/jobs.py`
- Create: `src/quant_trading/api/routes/agents.py`
- Modify: `src/quant_trading/api/main.py`
- Modify: `tests/integration/test_agents_jobs.py`
- Create: `tests/integration/test_agents_api.py`
- Modify: `tests/integration/test_runtime_auth.py`

- [ ] **Step 1: Add failing job API tests**

Append to `tests/integration/test_agents_jobs.py`:

```python
from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings


def test_market_analysis_job_api_submits_agent_job(monkeypatch, legacy_sqlite_db: Path):
    from quant_trading.jobs import runtime as runtime_module
    from quant_trading.agents.llm import FakeLLMClient

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient("市场研究报告"),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    response = client.post(
        "/jobs/agents/market-analysis",
        json={"symbol": "000001", "lookback_bars": 60, "mode": "overview"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "agent_market_analysis"
    assert payload["status"] == "succeeded"
    assert payload["result_payload"]["agent_type"] == "market_analysis"


def test_strategy_idea_job_api_submits_agent_job(monkeypatch):
    from quant_trading.jobs import runtime as runtime_module
    from quant_trading.agents.llm import FakeLLMClient

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient('{"thesis":"trend","entry_rules":["x"],"exit_rules":["y"],"risk_controls":["z"],"parameters_to_test":["p"],"data_requirements":["daily"],"failure_modes":["noise"],"backtest_readiness":"ready"}'),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    response = client.post(
        "/jobs/agents/strategy-idea",
        json={"idea": "Trend pullback strategy", "symbol": "000001"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "agent_strategy_idea"
    assert payload["status"] == "succeeded"
    assert payload["result_payload"]["agent_type"] == "strategy_idea"
```

- [ ] **Step 2: Add failing agent read API tests**

Create `tests/integration/test_agents_api.py`:

```python
from datetime import datetime
import json

from fastapi.testclient import TestClient

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import AgentRunRepository


def make_client_with_agent_run():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    with session_scope(engine) as session:
        row = AgentRunRepository(session).create_running(
            agent_type="market_analysis",
            symbol="000001",
            model_name="fake-llm",
            request_payload=json.dumps({"symbol": "000001"}),
            job_run_id=1,
            started_at=datetime(2026, 6, 24, 9, 0, 0),
        )
        AgentRunRepository(session).mark_succeeded(
            row,
            metrics_payload=json.dumps({"bar_count": 60}),
            result_payload=json.dumps({"research_only": True}),
            finished_at=datetime(2026, 6, 24, 9, 0, 1),
            duration_ms=1000,
        )
        agent_run_id = row.id
    return TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline"))), agent_run_id


def test_agent_runs_api_lists_and_gets_runs():
    client, agent_run_id = make_client_with_agent_run()

    list_response = client.get("/agent-runs", params={"agent_type": "market_analysis"})
    get_response = client.get(f"/agent-runs/{agent_run_id}")
    missing_response = client.get("/agent-runs/999")

    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [agent_run_id]
    assert get_response.status_code == 200
    assert get_response.json()["id"] == agent_run_id
    assert get_response.json()["metrics_payload"] == {"bar_count": 60}
    assert get_response.json()["result_payload"] == {"research_only": True}
    assert missing_response.status_code == 404
```

- [ ] **Step 3: Add failing auth tests**

Append to `tests/integration/test_runtime_auth.py`:

```python
def test_agent_runs_api_requires_auth_when_enabled():
    client = make_client()

    response = client.get("/agent-runs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_agent_jobs_api_requires_auth_when_enabled():
    client = make_client()

    response = client.post("/jobs/agents/strategy-idea", json={"idea": "x"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
```

- [ ] **Step 4: Run API tests and verify failure**

Run:

```bash
python -m pytest tests/integration/test_agents_jobs.py tests/integration/test_agents_api.py tests/integration/test_runtime_auth.py -q
```

Expected: FAIL because job constants, routes, and agent read route do not exist.

- [ ] **Step 5: Extend job runtime**

In `src/quant_trading/jobs/runtime.py`, import agent services:

```python
from quant_trading.agents.llm import DeepSeekLLMClient, LLMClient
from quant_trading.agents.models import MarketAnalysisRequest, StrategyIdeaRequest
from quant_trading.agents.service import run_market_analysis_agent, run_strategy_idea_agent
```

Add job-type constants:

```python
JOB_AGENT_MARKET_ANALYSIS = "agent_market_analysis"
JOB_AGENT_STRATEGY_IDEA = "agent_strategy_idea"
```

Include both in `SUPPORTED_JOB_TYPES`.

Add helper:

```python
def build_agent_llm_client(settings) -> LLMClient:
    return DeepSeekLLMClient.from_settings(settings)
```

Change `_execute_payload()` signature to accept settings explicitly:

```python
def _execute_payload(
    engine: Engine,
    job_type: str,
    payload: dict[str, Any],
    *,
    settings: AppSettings,
    cancellation_token: CancellationToken | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
```

Update the call inside `execute_job_run_with_engine()`:

```python
                lambda: _execute_payload(
                    engine,
                    job_type,
                    request_payload,
                    settings=_settings_from_agent_payload(request_payload),
                    cancellation_token=cancellation_token,
                    progress_callback=progress_callback,
                ),
```

Add helper functions near `_json_loads()`:

```python
def _settings_from_agent_payload(payload: dict[str, Any]) -> AppSettings:
    return AppSettings(
        deepseek_api_base=str(payload.get("deepseek_api_base") or "https://api.deepseek.com"),
        deepseek_model=str(payload.get("deepseek_model") or "deepseek-v4-pro"),
        agent_prompt_max_chars=int(payload.get("agent_prompt_max_chars") or 8000),
        agent_result_max_chars=int(payload.get("agent_result_max_chars") or 12000),
    )
```

Inside `_execute_payload()`, add:

```python
    if job_type == JOB_AGENT_MARKET_ANALYSIS:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        return run_market_analysis_agent(
            engine,
            MarketAnalysisRequest(
                symbol=str(payload["symbol"]),
                start=date.fromisoformat(payload["start"]) if payload.get("start") else None,
                end=date.fromisoformat(payload["end"]) if payload.get("end") else None,
                lookback_bars=int(payload.get("lookback_bars", 252)),
                mode=str(payload.get("mode", "overview")),
            ),
            llm_client=build_agent_llm_client(settings),
            job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
            settings=settings,
        )
    if job_type == JOB_AGENT_STRATEGY_IDEA:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        return run_strategy_idea_agent(
            engine,
            StrategyIdeaRequest(
                idea=str(payload["idea"]),
                symbol=str(payload["symbol"]) if payload.get("symbol") else None,
                market_context=str(payload["market_context"]) if payload.get("market_context") else None,
                constraints=payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {},
            ),
            llm_client=build_agent_llm_client(settings),
            job_run_id=int(payload["job_run_id"]) if payload.get("job_run_id") else None,
            settings=settings,
        )
```

Also import `date` from `datetime` and `AppSettings` from `quant_trading.config`.

When `execute_job_run_with_engine()` prepares request payload, add job id for both agent types:

```python
        if job_type in {MARKET_DATA_SYNC, JOB_AGENT_MARKET_ANALYSIS, JOB_AGENT_STRATEGY_IDEA}:
            request_payload = {**request_payload, "job_run_id": job_run_id}
```

- [ ] **Step 6: Add job submission endpoints**

In `src/quant_trading/api/routes/jobs.py`, import new constants:

```python
    JOB_AGENT_MARKET_ANALYSIS,
    JOB_AGENT_STRATEGY_IDEA,
```

Add request models:

```python
class AgentMarketAnalysisRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    start: str | None = None
    end: str | None = None
    lookback_bars: int = Field(default=252, ge=60, le=1000)
    mode: str = Field(default="overview", pattern="^(overview|risk|regime)$")


class AgentStrategyIdeaRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=4000)
    symbol: str | None = Field(default=None, max_length=32)
    market_context: str | None = Field(default=None, max_length=2000)
    constraints: dict[str, Any] = Field(default_factory=dict)
```

Add endpoints:

```python
@router.post("/agents/market-analysis")
def create_agent_market_analysis_job(
    payload: AgentMarketAnalysisRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            JOB_AGENT_MARKET_ANALYSIS,
            _agent_job_payload(payload.model_dump(mode="json"), request.app.state.settings),
            make_queue,
        )
    )


@router.post("/agents/strategy-idea")
def create_agent_strategy_idea_job(
    payload: AgentStrategyIdeaRequest,
    request: Request,
) -> dict[str, Any]:
    return _job_payload(
        submit_job_run(
            request.app.state.engine,
            request.app.state.settings,
            JOB_AGENT_STRATEGY_IDEA,
            _agent_job_payload(payload.model_dump(mode="json"), request.app.state.settings),
            make_queue,
        )
    )
```

Add helper near `_json_loads()`:

```python
def _agent_job_payload(payload: dict[str, Any], settings) -> dict[str, Any]:
    return {
        **payload,
        "deepseek_api_base": settings.deepseek_api_base,
        "deepseek_model": settings.deepseek_model,
        "agent_prompt_max_chars": settings.agent_prompt_max_chars,
        "agent_result_max_chars": settings.agent_result_max_chars,
    }
```

- [ ] **Step 7: Add agent read routes**

Create `src/quant_trading/api/routes/agents.py`:

```python
from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import AgentRunORM
from quant_trading.storage.repositories import AgentRunRepository

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


@router.get("")
def list_agent_runs(
    request: Request,
    agent_type: str | None = None,
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with session_scope(request.app.state.engine) as session:
        rows = AgentRunRepository(session).list_recent(
            agent_type=agent_type,
            status=status,
            symbol=symbol,
            limit=limit,
        )
        return [_agent_run_payload(row) for row in rows]


@router.get("/{agent_run_id}")
def get_agent_run(agent_run_id: int, request: Request) -> dict[str, Any]:
    with session_scope(request.app.state.engine) as session:
        row = AgentRunRepository(session).get(agent_run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        return _agent_run_payload(row)


def _agent_run_payload(row: AgentRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent_type": row.agent_type,
        "status": row.status,
        "symbol": row.symbol,
        "model_name": row.model_name,
        "request_payload": _json_loads(row.request_payload),
        "metrics_payload": _json_loads(row.metrics_payload),
        "result_payload": _json_loads(row.result_payload),
        "error_message": row.error_message,
        "job_run_id": row.job_run_id,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
        "created_at": _iso(row.created_at),
    }


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()
```

- [ ] **Step 8: Register agent read routes**

In `src/quant_trading/api/main.py`, add `agents` to the import tuple:

```python
    agents,
```

Register before `jobs.router`:

```python
    app.include_router(agents.router)
```

- [ ] **Step 9: Run API tests and verify pass**

Run:

```bash
python -m pytest tests/integration/test_agents_jobs.py tests/integration/test_agents_api.py tests/integration/test_runtime_auth.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit job and API integration**

Run:

```bash
git add src/quant_trading/jobs/runtime.py src/quant_trading/api/routes/jobs.py src/quant_trading/api/routes/agents.py src/quant_trading/api/main.py tests/integration/test_agents_jobs.py tests/integration/test_agents_api.py tests/integration/test_runtime_auth.py
git commit -m "feat: expose quant agent jobs and runs"
```

---

### Task 7: Documentation And Safety Regression Tests

**Files:**
- Modify: `README.md`
- Modify: `tests/integration/test_agents_jobs.py`
- Modify: `tests/unit/test_market_analysis_agent.py`
- Modify: `tests/unit/test_strategy_idea_agent.py`

- [ ] **Step 1: Add failing safety regression tests**

Append to `tests/integration/test_agents_jobs.py`:

```python
def test_agent_jobs_do_not_create_broker_order_events(monkeypatch, legacy_sqlite_db: Path):
    from quant_trading.jobs import runtime as runtime_module
    from quant_trading.agents.llm import FakeLLMClient
    from quant_trading.storage.models import BrokerOrderEventORM

    monkeypatch.setattr(
        runtime_module,
        "build_agent_llm_client",
        lambda settings: FakeLLMClient("市场研究报告"),
    )
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    import_legacy_sqlite(legacy_sqlite_db, engine)
    client = TestClient(create_app(engine=engine, settings=AppSettings(job_executor="inline")))

    response = client.post(
        "/jobs/agents/market-analysis",
        json={"symbol": "000001", "lookback_bars": 60},
    )

    assert response.status_code == 200
    with session_scope(engine) as session:
        assert session.query(BrokerOrderEventORM).count() == 0


def test_missing_llm_credentials_fail_cleanly():
    from quant_trading.agents.models import StrategyIdeaRequest
    from quant_trading.agents.service import run_strategy_idea_agent

    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    try:
        run_strategy_idea_agent(
            engine,
            StrategyIdeaRequest(idea="Trend following"),
            settings=AppSettings(deepseek_api_key=None),
        )
    except ValueError as exc:
        assert "DEEPSEEK_API_KEY is required for agent jobs" in str(exc)
    else:
        raise AssertionError("expected missing credential failure")
```

- [ ] **Step 2: Run safety tests and verify pass**

Run:

```bash
python -m pytest tests/integration/test_agents_jobs.py tests/unit/test_market_analysis_agent.py tests/unit/test_strategy_idea_agent.py -q
```

Expected: PASS.

- [ ] **Step 3: Update README**

In `README.md`, after the "Market Data Sync" section and before "Job Tasks", add:

```markdown
## Quant Agent v1

Quant Agent v1 adds audited research agents for market analysis and strategy idea structuring.
Agents run through the existing job runtime and store business-level audit rows in `agent_runs`.

Create a market analysis job:

```bash
curl -X POST http://127.0.0.1:8000/jobs/agents/market-analysis \
  -H "Content-Type: application/json" \
  -d '{"symbol":"000001","lookback_bars":252,"mode":"overview"}'
```

Create a strategy idea job:

```bash
curl -X POST http://127.0.0.1:8000/jobs/agents/strategy-idea \
  -H "Content-Type: application/json" \
  -d '{"idea":"Use moving-average pullbacks to structure a long-only trend research strategy.","symbol":"000001"}'
```

Inspect agent runs:

```bash
curl http://127.0.0.1:8000/agent-runs
curl http://127.0.0.1:8000/agent-runs/1
```

Agent jobs require:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | empty | Required for real LLM-backed agent jobs. |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com` | DeepSeek-compatible API base URL. |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | Model name used by the agent LLM client. |
| `QUANT_AGENT_PROMPT_MAX_CHARS` | `8000` | Maximum prompt characters sent by agent services. |
| `QUANT_AGENT_RESULT_MAX_CHARS` | `12000` | Maximum LLM result characters persisted by agent services. |

Agent outputs are research-only. They do not place orders, call broker adapters, approve strategies,
execute generated code, start paper runs, or provide buy/sell instructions. Strategy-code generation
and automatic trading are intentionally outside v1.
```

- [ ] **Step 4: Update endpoint list**

In the README endpoint list, add:

```text
http://localhost:8000/agent-runs
http://localhost:8000/agent-runs/{agent_run_id}
http://localhost:8000/jobs/agents/market-analysis
http://localhost:8000/jobs/agents/strategy-idea
```

- [ ] **Step 5: Commit docs and safety tests**

Run:

```bash
git add README.md tests/integration/test_agents_jobs.py tests/unit/test_market_analysis_agent.py tests/unit/test_strategy_idea_agent.py
git commit -m "docs: document quant agent v1"
```

---

### Task 8: Final Reviews And Verification

**Files:**
- Review all files changed by this feature.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
python -m pytest \
  tests/unit/test_settings.py \
  tests/unit/test_agent_llm.py \
  tests/unit/test_market_analysis_agent.py \
  tests/unit/test_strategy_idea_agent.py \
  tests/integration/test_agent_runs_repository.py \
  tests/integration/test_agents_api.py \
  tests/integration/test_agents_jobs.py \
  tests/integration/test_jobs_api.py \
  tests/integration/test_migrations.py \
  tests/integration/test_runtime_auth.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python -m pytest tests -q
```

Expected: PASS. If it fails because an optional external dependency is missing, capture the exact missing dependency and rerun the largest local subset that avoids that dependency.

- [ ] **Step 3: Run Spec Review**

Open `docs/superpowers/specs/2026-06-24-quant-agent-v1-design.md` and verify every required item has implementation evidence:

- `agent_runs` schema and repository exist.
- `MarketAnalysisAgent` computes deterministic metrics before LLM calls.
- `StrategyIdeaAgent` outputs strategy specs, not executable code.
- job types and job APIs exist.
- read APIs exist.
- settings exist and secret fields are redacted.
- payload and error caps exist.
- missing market data and missing LLM credentials fail cleanly.
- no broker adapter or paper trading path is called by agent jobs.
- README documents endpoints and safety boundary.

Expected: PASS with no missing spec item.

- [ ] **Step 4: Run Quality Review**

Review the diff for:

- no API key/token persistence
- no arbitrary generated-code execution
- no broker adapter imports in agent modules
- no paper trading imports in agent modules
- bounded request/result/error storage
- clear names and small modules
- tests covering success and failure paths
- migration downgrade correctness

Expected: PASS. Fix any finding before proceeding.

- [ ] **Step 5: Inspect final diff**

Run:

```bash
git diff --stat main...HEAD
git diff --check
```

Expected: no whitespace errors; diff only touches files listed in this plan.

- [ ] **Step 6: Commit final review fixes if any**

If Step 3 or Step 4 required fixes, commit them:

```bash
git add README.md migrations/versions/20260624_0007_add_agent_runs.py src/quant_trading tests
git commit -m "fix: address quant agent review findings"
```

If no fixes were required, skip this commit.

- [ ] **Step 7: Report implementation status**

Summarize:

- branch name
- commits created
- tests run and results
- spec review result
- quality review result
- any known limitations, especially real LLM calls requiring `DEEPSEEK_API_KEY`

---

## Completion Criteria

The feature is complete only when:

- All tasks above are checked.
- Targeted tests pass.
- Full local test suite passes or any dependency-related limitation is explicitly documented.
- Spec review passes.
- Quality review passes.
- `README.md` documents Quant Agent v1.
- The worktree is clean except for intentional uncommitted changes requested by the user.
