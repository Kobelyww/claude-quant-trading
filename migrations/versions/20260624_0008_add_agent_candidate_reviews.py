"""add agent candidate reviews

Revision ID: 20260624_0008
Revises: 20260624_0007
Create Date: 2026-06-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260624_0008"
down_revision = "20260624_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_candidate_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_agent_run_id",
            sa.Integer(),
            sa.ForeignKey("agent_runs.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("candidate_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("backtest_request_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("operator", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("operator_note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "backtest_job_run_id",
            sa.Integer(),
            sa.ForeignKey("job_runs.id"),
            nullable=True,
        ),
        sa.Column(
            "backtest_run_id",
            sa.Integer(),
            sa.ForeignKey("backtest_runs.id"),
            nullable=True,
        ),
        sa.Column(
            "review_agent_run_id",
            sa.Integer(),
            sa.ForeignKey("agent_runs.id"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "source_agent_run_id",
            name="uq_agent_candidate_reviews_source_agent_run_id",
        ),
    )
    op.create_index(
        "ix_agent_candidate_reviews_source_agent_run_id",
        "agent_candidate_reviews",
        ["source_agent_run_id"],
    )
    op.create_index(
        "ix_agent_candidate_reviews_status",
        "agent_candidate_reviews",
        ["status"],
    )
    op.create_index(
        "ix_agent_candidate_reviews_symbol",
        "agent_candidate_reviews",
        ["symbol"],
    )
    op.create_index(
        "ix_agent_candidate_reviews_strategy_name",
        "agent_candidate_reviews",
        ["strategy_name"],
    )
    op.create_index(
        "ix_agent_candidate_reviews_backtest_job_run_id",
        "agent_candidate_reviews",
        ["backtest_job_run_id"],
    )
    op.create_index(
        "ix_agent_candidate_reviews_backtest_run_id",
        "agent_candidate_reviews",
        ["backtest_run_id"],
    )
    op.create_index(
        "ix_agent_candidate_reviews_review_agent_run_id",
        "agent_candidate_reviews",
        ["review_agent_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_candidate_reviews_review_agent_run_id",
        table_name="agent_candidate_reviews",
    )
    op.drop_index(
        "ix_agent_candidate_reviews_backtest_run_id",
        table_name="agent_candidate_reviews",
    )
    op.drop_index(
        "ix_agent_candidate_reviews_backtest_job_run_id",
        table_name="agent_candidate_reviews",
    )
    op.drop_index(
        "ix_agent_candidate_reviews_strategy_name",
        table_name="agent_candidate_reviews",
    )
    op.drop_index("ix_agent_candidate_reviews_symbol", table_name="agent_candidate_reviews")
    op.drop_index("ix_agent_candidate_reviews_status", table_name="agent_candidate_reviews")
    op.drop_index(
        "ix_agent_candidate_reviews_source_agent_run_id",
        table_name="agent_candidate_reviews",
    )
    op.drop_table("agent_candidate_reviews")
