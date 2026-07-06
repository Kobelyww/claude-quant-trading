"""add agent memory skill review board

Revision ID: 20260706_0011
Revises: 20260626_0010
Create Date: 2026-07-06
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "20260706_0011"
down_revision = "20260626_0010"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    op.create_table(
        "strategy_skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "template_type",
            sa.String(length=64),
            nullable=False,
            server_default="deterministic_template",
        ),
        sa.Column(
            "supported_markets_payload",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "required_data_fields_payload",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "parameter_schema_payload",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "validation_rules_payload",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("risk_notes_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("prompt_guidance", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "skill_key",
            "version",
            name="uq_strategy_skills_key_version",
        ),
    )
    for name, columns in {
        "ix_strategy_skills_skill_key": ["skill_key"],
        "ix_strategy_skills_version": ["version"],
        "ix_strategy_skills_status": ["status"],
        "ix_strategy_skills_created_at": ["created_at"],
        "ix_strategy_skills_updated_at": ["updated_at"],
    }.items():
        op.create_index(name, "strategy_skills", columns)

    strategy_skills = sa.table(
        "strategy_skills",
        sa.column("skill_key", sa.String(length=64)),
        sa.column("version", sa.String(length=32)),
        sa.column("display_name", sa.String(length=128)),
        sa.column("description", sa.Text()),
        sa.column("status", sa.String(length=32)),
        sa.column("template_type", sa.String(length=64)),
        sa.column("supported_markets_payload", sa.Text()),
        sa.column("required_data_fields_payload", sa.Text()),
        sa.column("parameter_schema_payload", sa.Text()),
        sa.column("validation_rules_payload", sa.Text()),
        sa.column("risk_notes_payload", sa.Text()),
        sa.column("prompt_guidance", sa.Text()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    seed_time = datetime(2026, 7, 6, 0, 0, 0)
    op.bulk_insert(
        strategy_skills,
        [{**MA_CROSS_SKILL, "created_at": seed_time, "updated_at": seed_time}],
    )

    op.create_table(
        "agent_learning_memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("memory_type", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column(
            "strategy_skill_id",
            sa.Integer(),
            sa.ForeignKey("strategy_skills.id"),
            nullable=True,
        ),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("evidence_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "confidence",
            sa.Numeric(5, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "importance",
            sa.Numeric(5, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("retired_by", sa.String(length=128), nullable=True),
        sa.Column("retired_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "uq_agent_learning_memories_active_source_reason",
        "agent_learning_memories",
        ["memory_type", "source_type", "source_id", "reason_code"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )
    for name, columns in {
        "ix_agent_learning_memories_memory_type": ["memory_type"],
        "ix_agent_learning_memories_scope": ["scope"],
        "ix_agent_learning_memories_symbol": ["symbol"],
        "ix_agent_learning_memories_strategy_skill_id": ["strategy_skill_id"],
        "ix_agent_learning_memories_source_type": ["source_type"],
        "ix_agent_learning_memories_source_id": ["source_id"],
        "ix_agent_learning_memories_reason_code": ["reason_code"],
        "ix_agent_learning_memories_importance": ["importance"],
        "ix_agent_learning_memories_status": ["status"],
        "ix_agent_learning_memories_expires_at": ["expires_at"],
        "ix_agent_learning_memories_created_at": ["created_at"],
    }.items():
        op.create_index(name, "agent_learning_memories", columns)

    op.create_table(
        "agent_review_board_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column(
            "coordinator_agent_run_id",
            sa.Integer(),
            sa.ForeignKey("agent_runs.id"),
            nullable=True,
        ),
        sa.Column("final_recommendation", sa.String(length=64), nullable=True),
        sa.Column(
            "blocking_reason_codes_payload",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("memory_ids_payload", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("summary_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    for name, columns in {
        "ix_agent_review_board_runs_subject_type": ["subject_type"],
        "ix_agent_review_board_runs_subject_id": ["subject_id"],
        "ix_agent_review_board_runs_status": ["status"],
        "ix_agent_review_board_runs_coordinator_agent_run_id": [
            "coordinator_agent_run_id"
        ],
        "ix_agent_review_board_runs_final_recommendation": [
            "final_recommendation"
        ],
        "ix_agent_review_board_runs_created_at": ["created_at"],
    }.items():
        op.create_index(name, "agent_review_board_runs", columns)

    op.create_table(
        "agent_review_board_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "board_run_id",
            sa.Integer(),
            sa.ForeignKey("agent_review_board_runs.id"),
            nullable=False,
        ),
        sa.Column("reviewer_role", sa.String(length=64), nullable=False),
        sa.Column(
            "agent_run_id",
            sa.Integer(),
            sa.ForeignKey("agent_runs.id"),
            nullable=True,
        ),
        sa.Column("vote", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name, columns in {
        "ix_agent_review_board_votes_board_run_id": ["board_run_id"],
        "ix_agent_review_board_votes_reviewer_role": ["reviewer_role"],
        "ix_agent_review_board_votes_agent_run_id": ["agent_run_id"],
        "ix_agent_review_board_votes_vote": ["vote"],
        "ix_agent_review_board_votes_reason_code": ["reason_code"],
        "ix_agent_review_board_votes_created_at": ["created_at"],
    }.items():
        op.create_index(name, "agent_review_board_votes", columns)


def downgrade() -> None:
    for name in [
        "ix_agent_review_board_votes_created_at",
        "ix_agent_review_board_votes_reason_code",
        "ix_agent_review_board_votes_vote",
        "ix_agent_review_board_votes_agent_run_id",
        "ix_agent_review_board_votes_reviewer_role",
        "ix_agent_review_board_votes_board_run_id",
    ]:
        op.drop_index(name, table_name="agent_review_board_votes")
    op.drop_table("agent_review_board_votes")

    for name in [
        "ix_agent_review_board_runs_created_at",
        "ix_agent_review_board_runs_final_recommendation",
        "ix_agent_review_board_runs_coordinator_agent_run_id",
        "ix_agent_review_board_runs_status",
        "ix_agent_review_board_runs_subject_id",
        "ix_agent_review_board_runs_subject_type",
    ]:
        op.drop_index(name, table_name="agent_review_board_runs")
    op.drop_table("agent_review_board_runs")

    for name in [
        "ix_agent_learning_memories_created_at",
        "ix_agent_learning_memories_expires_at",
        "ix_agent_learning_memories_status",
        "ix_agent_learning_memories_importance",
        "ix_agent_learning_memories_reason_code",
        "ix_agent_learning_memories_source_id",
        "ix_agent_learning_memories_source_type",
        "ix_agent_learning_memories_strategy_skill_id",
        "ix_agent_learning_memories_symbol",
        "ix_agent_learning_memories_scope",
        "ix_agent_learning_memories_memory_type",
        "uq_agent_learning_memories_active_source_reason",
    ]:
        op.drop_index(name, table_name="agent_learning_memories")
    op.drop_table("agent_learning_memories")

    for name in [
        "ix_strategy_skills_updated_at",
        "ix_strategy_skills_created_at",
        "ix_strategy_skills_status",
        "ix_strategy_skills_version",
        "ix_strategy_skills_skill_key",
    ]:
        op.drop_index(name, table_name="strategy_skills")
    op.drop_table("strategy_skills")
