"""add scheduled operations

Revision ID: 20260623_0004
Revises: 20260623_0003
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0004"
down_revision = "20260623_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_run_id", sa.Integer(), sa.ForeignKey("job_runs.id"), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_job_events_job_run_id", "job_events", ["job_run_id"])
    op.create_index("ix_job_events_event_type", "job_events", ["event_type"])
    op.create_index("ix_job_events_created_at", "job_events", ["created_at"])

    op.create_table(
        "job_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("request_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("schedule_type", sa.String(length=32), nullable=False, server_default="interval"),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_job_run_id", sa.Integer(), sa.ForeignKey("job_runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_job_schedules_name", "job_schedules", ["name"], unique=True)
    op.create_index("ix_job_schedules_job_type", "job_schedules", ["job_type"])
    op.create_index("ix_job_schedules_enabled", "job_schedules", ["enabled"])
    op.create_index("ix_job_schedules_next_run_at", "job_schedules", ["next_run_at"])
    op.create_index("ix_job_schedules_last_job_run_id", "job_schedules", ["last_job_run_id"])


def downgrade() -> None:
    op.drop_index("ix_job_schedules_last_job_run_id", table_name="job_schedules")
    op.drop_index("ix_job_schedules_next_run_at", table_name="job_schedules")
    op.drop_index("ix_job_schedules_enabled", table_name="job_schedules")
    op.drop_index("ix_job_schedules_job_type", table_name="job_schedules")
    op.drop_index("ix_job_schedules_name", table_name="job_schedules")
    op.drop_table("job_schedules")

    op.drop_index("ix_job_events_created_at", table_name="job_events")
    op.drop_index("ix_job_events_event_type", table_name="job_events")
    op.drop_index("ix_job_events_job_run_id", table_name="job_events")
    op.drop_table("job_events")
