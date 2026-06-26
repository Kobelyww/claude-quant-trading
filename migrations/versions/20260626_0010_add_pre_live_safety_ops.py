"""add pre-live safety ops

Revision ID: 20260626_0010
Revises: 20260626_0009
Create Date: 2026-06-26
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "20260626_0010"
down_revision = "20260626_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_safety_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column(
            "kill_switch_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "dry_run_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "simulated_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "live_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("scope", name="uq_execution_safety_states_scope"),
    )
    op.create_index("ix_execution_safety_states_scope", "execution_safety_states", ["scope"])
    op.create_index(
        "ix_execution_safety_states_kill_switch_active",
        "execution_safety_states",
        ["kill_switch_active"],
    )
    op.create_index(
        "ix_execution_safety_states_dry_run_enabled",
        "execution_safety_states",
        ["dry_run_enabled"],
    )
    op.create_index(
        "ix_execution_safety_states_simulated_enabled",
        "execution_safety_states",
        ["simulated_enabled"],
    )
    op.create_index(
        "ix_execution_safety_states_live_enabled",
        "execution_safety_states",
        ["live_enabled"],
    )
    op.create_index(
        "ix_execution_safety_states_updated_at",
        "execution_safety_states",
        ["updated_at"],
    )

    safety_states = sa.table(
        "execution_safety_states",
        sa.column("scope", sa.String(length=64)),
        sa.column("kill_switch_active", sa.Boolean()),
        sa.column("dry_run_enabled", sa.Boolean()),
        sa.column("simulated_enabled", sa.Boolean()),
        sa.column("live_enabled", sa.Boolean()),
        sa.column("reason", sa.Text()),
        sa.column("updated_by", sa.String(length=128)),
        sa.column("updated_at", sa.DateTime()),
    )
    op.bulk_insert(
        safety_states,
        [
            {
                "scope": "global",
                "kill_switch_active": False,
                "dry_run_enabled": True,
                "simulated_enabled": True,
                "live_enabled": False,
                "reason": "default simulated and dry-run startup",
                "updated_by": "system",
                "updated_at": datetime(2026, 6, 26, 0, 0, 0),
            }
        ],
    )

    op.create_table(
        "operator_approval_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("operator_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_operator_approval_requests_resource",
        "operator_approval_requests",
        ["resource_type", "resource_id"],
    )
    op.create_index(
        "uq_operator_approval_requests_pending_resource",
        "operator_approval_requests",
        ["resource_type", "resource_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_operator_approval_requests_resource_type",
        "operator_approval_requests",
        ["resource_type"],
    )
    op.create_index(
        "ix_operator_approval_requests_resource_id",
        "operator_approval_requests",
        ["resource_id"],
    )
    op.create_index(
        "ix_operator_approval_requests_status",
        "operator_approval_requests",
        ["status"],
    )
    op.create_index(
        "ix_operator_approval_requests_reason_code",
        "operator_approval_requests",
        ["reason_code"],
    )
    op.create_index(
        "ix_operator_approval_requests_requested_at",
        "operator_approval_requests",
        ["requested_at"],
    )
    op.create_index(
        "ix_operator_approval_requests_decided_at",
        "operator_approval_requests",
        ["decided_at"],
    )
    op.create_index(
        "ix_operator_approval_requests_expires_at",
        "operator_approval_requests",
        ["expires_at"],
    )

    op.create_table(
        "execution_order_intents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("paper_run_id", sa.Integer(), sa.ForeignKey("paper_runs.id"), nullable=True),
        sa.Column("paper_order_id", sa.Integer(), sa.ForeignKey("paper_orders.id"), nullable=True),
        sa.Column("client_order_id", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("estimated_price", sa.Numeric(18, 6), nullable=True),
        sa.Column(
            "estimated_notional",
            sa.Numeric(24, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("broker_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("risk_profile_name", sa.String(length=128), nullable=False),
        sa.Column("risk_summary_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "approval_request_id",
            sa.Integer(),
            sa.ForeignKey("operator_approval_requests.id"),
            nullable=True,
        ),
        sa.Column("blocked_reason_code", sa.String(length=128), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "client_order_id",
            name="uq_execution_order_intents_client_order_id",
        ),
    )
    for name, columns in {
        "ix_execution_order_intents_source_type": ["source_type"],
        "ix_execution_order_intents_source_id": ["source_id"],
        "ix_execution_order_intents_paper_run_id": ["paper_run_id"],
        "ix_execution_order_intents_paper_order_id": ["paper_order_id"],
        "ix_execution_order_intents_client_order_id": ["client_order_id"],
        "ix_execution_order_intents_symbol": ["symbol"],
        "ix_execution_order_intents_instrument_id": ["instrument_id"],
        "ix_execution_order_intents_broker_mode": ["broker_mode"],
        "ix_execution_order_intents_status": ["status"],
        "ix_execution_order_intents_risk_profile_name": ["risk_profile_name"],
        "ix_execution_order_intents_approval_required": ["approval_required"],
        "ix_execution_order_intents_approval_request_id": ["approval_request_id"],
        "ix_execution_order_intents_blocked_reason_code": ["blocked_reason_code"],
        "ix_execution_order_intents_created_at": ["created_at"],
        "ix_execution_order_intents_updated_at": ["updated_at"],
        "ix_execution_order_intents_submitted_at": ["submitted_at"],
    }.items():
        op.create_index(name, "execution_order_intents", columns)

    op.create_table(
        "execution_order_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_intent_id",
            sa.Integer(),
            sa.ForeignKey("execution_order_intents.id"),
            nullable=False,
        ),
        sa.Column("decision_type", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("policy_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_execution_order_decisions_order_intent_id",
        "execution_order_decisions",
        ["order_intent_id"],
    )
    op.create_index(
        "ix_execution_order_decisions_decision_type",
        "execution_order_decisions",
        ["decision_type"],
    )
    op.create_index(
        "ix_execution_order_decisions_reason_code",
        "execution_order_decisions",
        ["reason_code"],
    )
    op.create_index(
        "ix_execution_order_decisions_created_at",
        "execution_order_decisions",
        ["created_at"],
    )

    op.create_table(
        "safety_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    for name, columns in {
        "ix_safety_incidents_severity": ["severity"],
        "ix_safety_incidents_category": ["category"],
        "ix_safety_incidents_status": ["status"],
        "ix_safety_incidents_resource_type": ["resource_type"],
        "ix_safety_incidents_resource_id": ["resource_id"],
        "ix_safety_incidents_reason_code": ["reason_code"],
        "ix_safety_incidents_created_at": ["created_at"],
    }.items():
        op.create_index(name, "safety_incidents", columns)

    op.create_table(
        "kill_switch_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("previous_state_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("new_state_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("operator", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_kill_switch_events_scope", "kill_switch_events", ["scope"])
    op.create_index(
        "ix_kill_switch_events_created_at",
        "kill_switch_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_kill_switch_events_created_at", table_name="kill_switch_events")
    op.drop_index("ix_kill_switch_events_scope", table_name="kill_switch_events")
    op.drop_table("kill_switch_events")

    op.drop_index("ix_safety_incidents_created_at", table_name="safety_incidents")
    op.drop_index("ix_safety_incidents_reason_code", table_name="safety_incidents")
    op.drop_index("ix_safety_incidents_resource_id", table_name="safety_incidents")
    op.drop_index("ix_safety_incidents_resource_type", table_name="safety_incidents")
    op.drop_index("ix_safety_incidents_status", table_name="safety_incidents")
    op.drop_index("ix_safety_incidents_category", table_name="safety_incidents")
    op.drop_index("ix_safety_incidents_severity", table_name="safety_incidents")
    op.drop_table("safety_incidents")

    op.drop_index(
        "ix_execution_order_decisions_created_at",
        table_name="execution_order_decisions",
    )
    op.drop_index(
        "ix_execution_order_decisions_reason_code",
        table_name="execution_order_decisions",
    )
    op.drop_index(
        "ix_execution_order_decisions_decision_type",
        table_name="execution_order_decisions",
    )
    op.drop_index(
        "ix_execution_order_decisions_order_intent_id",
        table_name="execution_order_decisions",
    )
    op.drop_table("execution_order_decisions")

    for name in [
        "ix_execution_order_intents_submitted_at",
        "ix_execution_order_intents_updated_at",
        "ix_execution_order_intents_created_at",
        "ix_execution_order_intents_blocked_reason_code",
        "ix_execution_order_intents_approval_request_id",
        "ix_execution_order_intents_approval_required",
        "ix_execution_order_intents_risk_profile_name",
        "ix_execution_order_intents_status",
        "ix_execution_order_intents_broker_mode",
        "ix_execution_order_intents_instrument_id",
        "ix_execution_order_intents_symbol",
        "ix_execution_order_intents_client_order_id",
        "ix_execution_order_intents_paper_order_id",
        "ix_execution_order_intents_paper_run_id",
        "ix_execution_order_intents_source_id",
        "ix_execution_order_intents_source_type",
    ]:
        op.drop_index(name, table_name="execution_order_intents")
    op.drop_table("execution_order_intents")

    for name in [
        "ix_operator_approval_requests_expires_at",
        "ix_operator_approval_requests_decided_at",
        "ix_operator_approval_requests_requested_at",
        "ix_operator_approval_requests_reason_code",
        "ix_operator_approval_requests_status",
        "ix_operator_approval_requests_resource_id",
        "ix_operator_approval_requests_resource_type",
        "uq_operator_approval_requests_pending_resource",
        "ix_operator_approval_requests_resource",
    ]:
        op.drop_index(name, table_name="operator_approval_requests")
    op.drop_table("operator_approval_requests")

    for name in [
        "ix_execution_safety_states_updated_at",
        "ix_execution_safety_states_live_enabled",
        "ix_execution_safety_states_simulated_enabled",
        "ix_execution_safety_states_dry_run_enabled",
        "ix_execution_safety_states_kill_switch_active",
        "ix_execution_safety_states_scope",
    ]:
        op.drop_index(name, table_name="execution_safety_states")
    op.drop_table("execution_safety_states")
