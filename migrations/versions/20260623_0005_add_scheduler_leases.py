"""add scheduler leases

Revision ID: 20260623_0005
Revises: 20260623_0004
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0005"
down_revision = "20260623_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_schedules", sa.Column("locked_until", sa.DateTime(), nullable=True))
    op.add_column("job_schedules", sa.Column("locked_by", sa.String(length=128), nullable=True))
    op.add_column("job_schedules", sa.Column("lock_acquired_at", sa.DateTime(), nullable=True))
    op.create_index("ix_job_schedules_locked_until", "job_schedules", ["locked_until"])


def downgrade() -> None:
    op.drop_index("ix_job_schedules_locked_until", table_name="job_schedules")
    op.drop_column("job_schedules", "lock_acquired_at")
    op.drop_column("job_schedules", "locked_by")
    op.drop_column("job_schedules", "locked_until")
