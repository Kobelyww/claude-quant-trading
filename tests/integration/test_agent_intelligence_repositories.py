from datetime import datetime, timedelta
from decimal import Decimal
import json

from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import (
    AgentLearningMemoryRepository,
    AgentReviewBoardRunRepository,
    AgentReviewBoardVoteRepository,
    StrategySkillRepository,
)


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def _create_memory(
    repo: AgentLearningMemoryRepository,
    *,
    source_id: int,
    reason_code: str,
    now: datetime,
    title: str,
    scope: str = "global",
    symbol: str | None = None,
    strategy_skill_id: int | None = None,
    importance: Decimal = Decimal("0.5"),
    status_retired: bool = False,
    expires_at: datetime | None = None,
):
    row, created = repo.get_or_create_active(
        memory_type="strategy_failure",
        scope=scope,
        source_type="research_validation_report",
        source_id=source_id,
        reason_code=reason_code,
        title=title,
        content=f"{title} content",
        evidence_payload={"source_id": source_id},
        confidence=Decimal("0.8"),
        importance=importance,
        now=now,
        symbol=symbol,
        strategy_skill_id=strategy_skill_id,
        expires_at=expires_at,
    )
    assert created is True
    if status_retired:
        repo.retire(
            row.id,
            retired_by="tester",
            retired_reason="superseded",
            now=now + timedelta(minutes=1),
        )
    return row


def test_strategy_skill_repository_seeds_and_lists_ma_cross():
    engine = make_engine_with_schema()
    now = datetime(2026, 7, 6, 9, 0, 0)

    with session_scope(engine) as session:
        repo = StrategySkillRepository(session)
        first_seed = repo.ensure_seeded(now)
        second_seed = repo.ensure_seeded(now + timedelta(minutes=1))
        skill = repo.get_active("ma_cross")
        active_skills = repo.list_active()

        assert skill is not None
        assert second_seed.id == first_seed.id
        assert skill.version == "1.0.0"
        assert skill.status == "active"
        assert [row.skill_key for row in active_skills].count("ma_cross") == 1


def test_learning_memory_repository_creates_reuses_and_retires_active_memory():
    engine = make_engine_with_schema()
    now = datetime(2026, 7, 6, 9, 0, 0)

    with session_scope(engine) as session:
        repo = AgentLearningMemoryRepository(session)
        row, created = repo.get_or_create_active(
            memory_type="operator_decision",
            scope="global",
            source_type="candidate_review",
            source_id=12,
            reason_code="candidate_rejected",
            title="Rejected candidate",
            content="Rejected after validation gaps.",
            evidence_payload={"candidate_review_id": 12},
            confidence=Decimal("1"),
            importance=Decimal("0.8"),
            now=now,
        )
        same_row, same_created = repo.get_or_create_active(
            memory_type="operator_decision",
            scope="global",
            source_type="candidate_review",
            source_id=12,
            reason_code="candidate_rejected",
            title="Rejected candidate duplicate",
            content="Duplicate content should not replace active row.",
            evidence_payload={"candidate_review_id": 12, "duplicate": True},
            confidence=Decimal("0.5"),
            importance=Decimal("0.1"),
            now=now + timedelta(minutes=1),
        )

        assert created is True
        assert same_created is False
        assert same_row.id == row.id
        assert same_row.title == "Rejected candidate"

        retired = repo.retire(
            row.id,
            retired_by="operator",
            retired_reason="superseded",
            now=now + timedelta(minutes=2),
        )
        first_retired_by = retired.retired_by
        first_retired_reason = retired.retired_reason
        first_retired_at = retired.retired_at
        retry_retired = repo.retire(
            row.id,
            retired_by="retry-operator",
            retired_reason="retry should not rewrite retirement metadata",
            now=now + timedelta(minutes=4),
        )
        new_row, new_created = repo.get_or_create_active(
            memory_type="operator_decision",
            scope="global",
            source_type="candidate_review",
            source_id=12,
            reason_code="candidate_rejected",
            title="Rejected candidate replacement",
            content="A new active lesson can replace retired memory.",
            evidence_payload={"candidate_review_id": 12, "replacement": True},
            confidence=Decimal("0.9"),
            importance=Decimal("0.7"),
            now=now + timedelta(minutes=3),
        )

        assert retired.status == "retired"
        assert retired.retired_by == "operator"
        assert retry_retired.status == "retired"
        assert retry_retired.retired_by == first_retired_by
        assert retry_retired.retired_reason == first_retired_reason
        assert retry_retired.retired_at == first_retired_at
        assert new_created is True
        assert new_row.id != row.id
        assert new_row.status == "active"


def test_learning_memory_repository_reuses_overlong_capped_identity_fields():
    engine = make_engine_with_schema()
    now = datetime(2026, 7, 6, 9, 0, 0)
    memory_type = "strategy_failure_" + ("x" * 80)
    source_type = "research_validation_report_" + ("y" * 80)
    reason_code = "parameter_overfit_" + ("z" * 160)

    with session_scope(engine) as session:
        repo = AgentLearningMemoryRepository(session)
        row, created = repo.get_or_create_active(
            memory_type=memory_type,
            scope="global",
            source_type=source_type,
            source_id=123,
            reason_code=reason_code,
            title="Overlong identity",
            content="Overlong identity fields should be canonicalized.",
            evidence_payload={"source_id": 123},
            confidence=Decimal("0.8"),
            importance=Decimal("0.7"),
            now=now,
        )
        same_row, same_created = repo.get_or_create_active(
            memory_type=memory_type,
            scope="global",
            source_type=source_type,
            source_id=123,
            reason_code=reason_code,
            title="Overlong identity duplicate",
            content="Repeated overlong identity values should reuse the row.",
            evidence_payload={"source_id": 123, "duplicate": True},
            confidence=Decimal("0.4"),
            importance=Decimal("0.3"),
            now=now + timedelta(minutes=1),
        )

        assert created is True
        assert same_created is False
        assert same_row.id == row.id
        assert same_row.memory_type == memory_type[:64]
        assert same_row.source_type == source_type[:64]
        assert same_row.reason_code == reason_code[:128]


def test_learning_memory_repository_retrieves_symbol_and_skill_scoped_memories_first():
    engine = make_engine_with_schema()
    now = datetime(2026, 7, 6, 9, 0, 0)

    with session_scope(engine) as session:
        skill = StrategySkillRepository(session).ensure_seeded(now)
        repo = AgentLearningMemoryRepository(session)
        _create_memory(
            repo,
            source_id=1,
            reason_code="global_lesson",
            now=now,
            title="global lesson",
            importance=Decimal("0.99"),
        )
        _create_memory(
            repo,
            source_id=2,
            reason_code="symbol_lesson",
            now=now + timedelta(minutes=1),
            title="symbol lesson",
            scope="symbol",
            symbol="000001",
            importance=Decimal("0.4"),
        )
        _create_memory(
            repo,
            source_id=3,
            reason_code="skill_lesson",
            now=now + timedelta(minutes=2),
            title="skill lesson",
            scope="strategy_skill",
            strategy_skill_id=skill.id,
            importance=Decimal("0.3"),
        )
        _create_memory(
            repo,
            source_id=4,
            reason_code="retired_lesson",
            now=now + timedelta(minutes=3),
            title="retired lesson",
            status_retired=True,
        )
        _create_memory(
            repo,
            source_id=5,
            reason_code="expired_lesson",
            now=now + timedelta(minutes=4),
            title="expired lesson",
            expires_at=now - timedelta(days=1),
        )

        rows = repo.list_active(
            symbol="000001",
            strategy_skill_id=skill.id,
            limit=10,
            now=now,
        )

        titles = [row.title for row in rows]
        assert set(titles[:2]) == {"symbol lesson", "skill lesson"}
        assert titles[2] == "global lesson"
        assert "retired lesson" not in titles
        assert "expired lesson" not in titles


def test_review_board_repositories_record_run_and_votes():
    engine = make_engine_with_schema()
    now = datetime(2026, 7, 6, 9, 0, 0)
    roles = [
        "data_steward",
        "strategy_researcher",
        "risk_officer",
        "validation_reviewer",
        "operations_reviewer",
    ]

    with session_scope(engine) as session:
        run_repo = AgentReviewBoardRunRepository(session)
        vote_repo = AgentReviewBoardVoteRepository(session)
        board_run = run_repo.create_running(
            subject_type="strategy_candidate",
            subject_id=99,
            memory_ids=[1, 2],
            now=now,
        )
        for index, role in enumerate(roles):
            vote_repo.record(
                board_run_id=board_run.id,
                reviewer_role=role,
                vote="needs_review" if role == "validation_reviewer" else "pass",
                reason_code=f"{role}_reason",
                rationale=f"{role} rationale",
                evidence_payload={"role": role, "index": index},
                now=now + timedelta(seconds=index),
            )
        run_repo.mark_completed(
            board_run.id,
            final_recommendation="needs_more_research",
            blocking_reason_codes=["validation_needs_review"],
            summary_payload={"final": "needs_more_research"},
            finished_at=now + timedelta(minutes=1),
            duration_ms=60000,
        )

        recent = run_repo.list_recent(limit=10)
        votes = vote_repo.list_for_board(board_run.id)

        assert recent[0].id == board_run.id
        assert recent[0].status == "completed"
        assert recent[0].final_recommendation == "needs_more_research"
        assert json.loads(recent[0].memory_ids_payload) == [1, 2]
        assert len(votes) == 5
        assert {vote.reviewer_role for vote in votes} == set(roles)
        assert json.loads(votes[0].evidence_payload)["role"] == "data_steward"
