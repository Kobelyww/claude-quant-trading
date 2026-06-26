"""add validation reports

Revision ID: 20260626_0009
Revises: 20260624_0008
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260626_0009"
down_revision = "20260624_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_quality_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_review_id",
            sa.Integer(),
            sa.ForeignKey("agent_candidate_reviews.id"),
            nullable=True,
        ),
        sa.Column(
            "backtest_run_id",
            sa.Integer(),
            sa.ForeignKey("backtest_runs.id"),
            nullable=True,
        ),
        sa.Column(
            "job_run_id",
            sa.Integer(),
            sa.ForeignKey("job_runs.id"),
            nullable=True,
        ),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("adjusted", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("bar_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_bar_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_bar_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "duplicate_timestamp_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "non_positive_price_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "non_positive_volume_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("invalid_ohlc_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stale_data", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("data_fingerprint", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("findings_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_data_quality_reports_candidate_review_id",
        "data_quality_reports",
        ["candidate_review_id"],
    )
    op.create_index(
        "ix_data_quality_reports_backtest_run_id",
        "data_quality_reports",
        ["backtest_run_id"],
    )
    op.create_index(
        "ix_data_quality_reports_job_run_id",
        "data_quality_reports",
        ["job_run_id"],
    )
    op.create_index("ix_data_quality_reports_symbol", "data_quality_reports", ["symbol"])
    op.create_index("ix_data_quality_reports_status", "data_quality_reports", ["status"])
    op.create_index("ix_data_quality_reports_severity", "data_quality_reports", ["severity"])
    op.create_index(
        "ix_data_quality_reports_symbol_start_date_end_date",
        "data_quality_reports",
        ["symbol", "start_date", "end_date"],
    )

    op.create_table(
        "research_validation_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_review_id",
            sa.Integer(),
            sa.ForeignKey("agent_candidate_reviews.id"),
            nullable=False,
        ),
        sa.Column(
            "source_backtest_run_id",
            sa.Integer(),
            sa.ForeignKey("backtest_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "data_quality_report_id",
            sa.Integer(),
            sa.ForeignKey("data_quality_reports.id"),
            nullable=True,
        ),
        sa.Column(
            "job_run_id",
            sa.Integer(),
            sa.ForeignKey("job_runs.id"),
            nullable=True,
        ),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column(
            "validation_status",
            sa.String(length=32),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "readiness_floor",
            sa.String(length=32),
            nullable=False,
            server_default="not_ready",
        ),
        sa.Column(
            "in_sample_metrics_payload",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "out_of_sample_metrics_payload",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("walk_forward_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "parameter_sensitivity_payload",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("benchmark_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("summary_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "candidate_review_id",
            name="uq_research_validation_reports_candidate_review_id",
        ),
    )
    op.create_index(
        "ix_research_validation_reports_candidate_review_id",
        "research_validation_reports",
        ["candidate_review_id"],
    )
    op.create_index(
        "ix_research_validation_reports_source_backtest_run_id",
        "research_validation_reports",
        ["source_backtest_run_id"],
    )
    op.create_index(
        "ix_research_validation_reports_data_quality_report_id",
        "research_validation_reports",
        ["data_quality_report_id"],
    )
    op.create_index(
        "ix_research_validation_reports_job_run_id",
        "research_validation_reports",
        ["job_run_id"],
    )
    op.create_index(
        "ix_research_validation_reports_symbol",
        "research_validation_reports",
        ["symbol"],
    )
    op.create_index(
        "ix_research_validation_reports_strategy_name",
        "research_validation_reports",
        ["strategy_name"],
    )
    op.create_index(
        "ix_research_validation_reports_validation_status",
        "research_validation_reports",
        ["validation_status"],
    )

    with op.batch_alter_table("agent_candidate_reviews") as batch_op:
        batch_op.add_column(
            sa.Column(
                "data_quality_report_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "research_validation_report_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_agent_candidate_reviews_data_quality_report_id",
            "data_quality_reports",
            ["data_quality_report_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_agent_candidate_reviews_research_validation_report_id",
            "research_validation_reports",
            ["research_validation_report_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_agent_candidate_reviews_data_quality_report_id",
            ["data_quality_report_id"],
        )
        batch_op.create_index(
            "ix_agent_candidate_reviews_research_validation_report_id",
            ["research_validation_report_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_candidate_reviews") as batch_op:
        batch_op.drop_index("ix_agent_candidate_reviews_research_validation_report_id")
        batch_op.drop_index("ix_agent_candidate_reviews_data_quality_report_id")
        batch_op.drop_constraint(
            "fk_agent_candidate_reviews_research_validation_report_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_agent_candidate_reviews_data_quality_report_id",
            type_="foreignkey",
        )
        batch_op.drop_column("research_validation_report_id")
        batch_op.drop_column("data_quality_report_id")

    op.drop_index(
        "ix_research_validation_reports_validation_status",
        table_name="research_validation_reports",
    )
    op.drop_index(
        "ix_research_validation_reports_strategy_name",
        table_name="research_validation_reports",
    )
    op.drop_index(
        "ix_research_validation_reports_symbol",
        table_name="research_validation_reports",
    )
    op.drop_index(
        "ix_research_validation_reports_job_run_id",
        table_name="research_validation_reports",
    )
    op.drop_index(
        "ix_research_validation_reports_data_quality_report_id",
        table_name="research_validation_reports",
    )
    op.drop_index(
        "ix_research_validation_reports_source_backtest_run_id",
        table_name="research_validation_reports",
    )
    op.drop_index(
        "ix_research_validation_reports_candidate_review_id",
        table_name="research_validation_reports",
    )
    op.drop_table("research_validation_reports")

    op.drop_index(
        "ix_data_quality_reports_symbol_start_date_end_date",
        table_name="data_quality_reports",
    )
    op.drop_index("ix_data_quality_reports_severity", table_name="data_quality_reports")
    op.drop_index("ix_data_quality_reports_status", table_name="data_quality_reports")
    op.drop_index("ix_data_quality_reports_symbol", table_name="data_quality_reports")
    op.drop_index("ix_data_quality_reports_job_run_id", table_name="data_quality_reports")
    op.drop_index(
        "ix_data_quality_reports_backtest_run_id",
        table_name="data_quality_reports",
    )
    op.drop_index(
        "ix_data_quality_reports_candidate_review_id",
        table_name="data_quality_reports",
    )
    op.drop_table("data_quality_reports")
