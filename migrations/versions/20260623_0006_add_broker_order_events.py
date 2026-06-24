"""add broker order events

Revision ID: 20260623_0006
Revises: 20260623_0005
Create Date: 2026-06-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0006"
down_revision = "20260623_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("paper_runs.id"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("paper_orders.id"), nullable=True),
        sa.Column("broker_mode", sa.String(length=32), nullable=False),
        sa.Column("client_order_id", sa.String(length=128), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("request_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("message", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_broker_order_events_run_id", "broker_order_events", ["run_id"])
    op.create_index("ix_broker_order_events_order_id", "broker_order_events", ["order_id"])
    op.create_index("ix_broker_order_events_broker_mode", "broker_order_events", ["broker_mode"])
    op.create_index(
        "ix_broker_order_events_client_order_id",
        "broker_order_events",
        ["client_order_id"],
    )
    op.create_index(
        "ix_broker_order_events_broker_order_id",
        "broker_order_events",
        ["broker_order_id"],
    )
    op.create_index("ix_broker_order_events_status", "broker_order_events", ["status"])
    op.create_index("ix_broker_order_events_accepted", "broker_order_events", ["accepted"])
    op.create_index("ix_broker_order_events_created_at", "broker_order_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_broker_order_events_created_at", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_accepted", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_status", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_broker_order_id", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_client_order_id", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_broker_mode", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_order_id", table_name="broker_order_events")
    op.drop_index("ix_broker_order_events_run_id", table_name="broker_order_events")
    op.drop_table("broker_order_events")
