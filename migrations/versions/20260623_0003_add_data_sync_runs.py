"""add data sync runs

Revision ID: 20260623_0003
Revises: 20260623_0002
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0003"
down_revision = "20260623_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("imported_bars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("job_run_id", sa.Integer(), sa.ForeignKey("job_runs.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_data_sync_runs_provider", "data_sync_runs", ["provider"])
    op.create_index("ix_data_sync_runs_symbol", "data_sync_runs", ["symbol"])
    op.create_index("ix_data_sync_runs_status", "data_sync_runs", ["status"])
    op.create_index("ix_data_sync_runs_job_run_id", "data_sync_runs", ["job_run_id"])


def downgrade() -> None:
    op.drop_index("ix_data_sync_runs_job_run_id", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_status", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_symbol", table_name="data_sync_runs")
    op.drop_index("ix_data_sync_runs_provider", table_name="data_sync_runs")
    op.drop_table("data_sync_runs")
