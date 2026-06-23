"""initial runtime schema

Revision ID: 20260622_0001
Revises:
Create Date: 2026-06-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260622_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("initial_cash", sa.Numeric(18, 6), nullable=False),
        sa.Column("final_equity", sa.Numeric(18, 6), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_backtest_runs_strategy_name", "backtest_runs", ["strategy_name"])
    op.create_index("ix_backtest_runs_symbol", "backtest_runs", ["symbol"])

    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_instruments_market", "instruments", ["market"])
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=True)

    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("base_currency", sa.String(length=16), nullable=False),
        sa.Column("initial_cash", sa.Numeric(18, 6), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("command_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_object_type", sa.String(length=64), nullable=True),
        sa.Column("created_object_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_workflow_runs_command_name", "workflow_runs", ["command_name"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    op.create_table(
        "backtest_equity_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("timestamp", sa.Date(), nullable=False),
        sa.Column("equity", sa.Numeric(18, 6), nullable=False),
        sa.Column("cash", sa.Numeric(18, 6), nullable=False),
        sa.Column("market_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("drawdown", sa.Numeric(18, 6), nullable=False),
    )
    op.create_index(
        "ix_backtest_equity_points_run_id",
        "backtest_equity_points",
        ["run_id"],
    )
    op.create_index(
        "ix_backtest_equity_points_timestamp",
        "backtest_equity_points",
        ["timestamp"],
    )

    op.create_table(
        "backtest_fills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(18, 6), nullable=False),
        sa.Column("commission", sa.Numeric(18, 6), nullable=False),
        sa.Column("slippage", sa.Numeric(18, 6), nullable=False),
        sa.Column("filled_at", sa.Date(), nullable=False),
    )
    op.create_index("ix_backtest_fills_run_id", "backtest_fills", ["run_id"])

    op.create_table(
        "backtest_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("submitted_at", sa.Date(), nullable=False),
    )
    op.create_index("ix_backtest_orders_run_id", "backtest_orders", ["run_id"])

    op.create_table(
        "market_bars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("timestamp", sa.Date(), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("open", sa.Numeric(18, 6), nullable=False),
        sa.Column("high", sa.Numeric(18, 6), nullable=False),
        sa.Column("low", sa.Numeric(18, 6), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.Numeric(24, 6), nullable=False),
        sa.Column("amount", sa.Numeric(24, 6), nullable=True),
        sa.Column("adjusted", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("ingestion_batch_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "instrument_id",
            "timestamp",
            "timeframe",
            "adjusted",
            "source",
            name="uq_market_bar_identity",
        ),
    )
    op.create_index("ix_market_bars_instrument_id", "market_bars", ["instrument_id"])
    op.create_index("ix_market_bars_timestamp", "market_bars", ["timestamp"])

    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("market_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(18, 6), nullable=False),
        sa.Column("updated_at", sa.Date(), nullable=False),
        sa.UniqueConstraint(
            "account_id",
            "instrument_id",
            name="uq_paper_position_account_instrument",
        ),
    )
    op.create_index("ix_paper_positions_account_id", "paper_positions", ["account_id"])
    op.create_index("ix_paper_positions_instrument_id", "paper_positions", ["instrument_id"])
    op.create_index("ix_paper_positions_symbol", "paper_positions", ["symbol"])

    op.create_table(
        "paper_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("universe_config", sa.String(length=2048), nullable=False),
        sa.Column("strategy_config", sa.String(length=2048), nullable=False),
        sa.Column("risk_config", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_processed_at", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_paper_runs_account_id", "paper_runs", ["account_id"])
    op.create_index("ix_paper_runs_strategy_name", "paper_runs", ["strategy_name"])
    op.create_index("ix_paper_runs_symbol", "paper_runs", ["symbol"])
    op.create_index("ix_paper_runs_status", "paper_runs", ["status"])

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("paper_runs.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("risk_decision", sa.String(length=32), nullable=True),
        sa.Column("submitted_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_paper_orders_account_id", "paper_orders", ["account_id"])
    op.create_index("ix_paper_orders_instrument_id", "paper_orders", ["instrument_id"])
    op.create_index("ix_paper_orders_run_id", "paper_orders", ["run_id"])
    op.create_index("ix_paper_orders_status", "paper_orders", ["status"])
    op.create_index("ix_paper_orders_symbol", "paper_orders", ["symbol"])

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("paper_runs.id"), nullable=True),
        sa.Column("timestamp", sa.Date(), nullable=False),
        sa.Column("equity", sa.Numeric(18, 6), nullable=False),
        sa.Column("cash", sa.Numeric(18, 6), nullable=False),
        sa.Column("market_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(18, 6), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(18, 6), nullable=False),
        sa.Column("drawdown", sa.Numeric(18, 6), nullable=False),
    )
    op.create_index("ix_portfolio_snapshots_account_id", "portfolio_snapshots", ["account_id"])
    op.create_index("ix_portfolio_snapshots_run_id", "portfolio_snapshots", ["run_id"])

    op.create_table(
        "paper_fills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("paper_runs.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("paper_orders.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(18, 6), nullable=False),
        sa.Column("commission", sa.Numeric(18, 6), nullable=False),
        sa.Column("slippage", sa.Numeric(18, 6), nullable=False),
        sa.Column("filled_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_paper_fills_account_id", "paper_fills", ["account_id"])
    op.create_index("ix_paper_fills_instrument_id", "paper_fills", ["instrument_id"])
    op.create_index("ix_paper_fills_order_id", "paper_fills", ["order_id"])
    op.create_index("ix_paper_fills_run_id", "paper_fills", ["run_id"])
    op.create_index("ix_paper_fills_symbol", "paper_fills", ["symbol"])

    op.create_table(
        "risk_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("paper_runs.id"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("paper_orders.id"), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("rule_name", sa.String(length=128), nullable=False),
        sa.Column("message", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_risk_decisions_order_id", "risk_decisions", ["order_id"])
    op.create_index("ix_risk_decisions_run_id", "risk_decisions", ["run_id"])

    op.create_table(
        "cash_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("paper_runs.id"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("paper_orders.id"), nullable=True),
        sa.Column("fill_id", sa.Integer(), sa.ForeignKey("paper_fills.id"), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("cash_after", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cash_ledger_account_id", "cash_ledger", ["account_id"])
    op.create_index("ix_cash_ledger_event_type", "cash_ledger", ["event_type"])
    op.create_index("ix_cash_ledger_fill_id", "cash_ledger", ["fill_id"])
    op.create_index("ix_cash_ledger_order_id", "cash_ledger", ["order_id"])
    op.create_index("ix_cash_ledger_run_id", "cash_ledger", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_cash_ledger_run_id", table_name="cash_ledger")
    op.drop_index("ix_cash_ledger_order_id", table_name="cash_ledger")
    op.drop_index("ix_cash_ledger_fill_id", table_name="cash_ledger")
    op.drop_index("ix_cash_ledger_event_type", table_name="cash_ledger")
    op.drop_index("ix_cash_ledger_account_id", table_name="cash_ledger")
    op.drop_table("cash_ledger")

    op.drop_index("ix_risk_decisions_run_id", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_order_id", table_name="risk_decisions")
    op.drop_table("risk_decisions")

    op.drop_index("ix_paper_fills_symbol", table_name="paper_fills")
    op.drop_index("ix_paper_fills_run_id", table_name="paper_fills")
    op.drop_index("ix_paper_fills_order_id", table_name="paper_fills")
    op.drop_index("ix_paper_fills_instrument_id", table_name="paper_fills")
    op.drop_index("ix_paper_fills_account_id", table_name="paper_fills")
    op.drop_table("paper_fills")

    op.drop_index("ix_portfolio_snapshots_run_id", table_name="portfolio_snapshots")
    op.drop_index("ix_portfolio_snapshots_account_id", table_name="portfolio_snapshots")
    op.drop_table("portfolio_snapshots")

    op.drop_index("ix_paper_orders_symbol", table_name="paper_orders")
    op.drop_index("ix_paper_orders_status", table_name="paper_orders")
    op.drop_index("ix_paper_orders_run_id", table_name="paper_orders")
    op.drop_index("ix_paper_orders_instrument_id", table_name="paper_orders")
    op.drop_index("ix_paper_orders_account_id", table_name="paper_orders")
    op.drop_table("paper_orders")

    op.drop_index("ix_paper_runs_status", table_name="paper_runs")
    op.drop_index("ix_paper_runs_symbol", table_name="paper_runs")
    op.drop_index("ix_paper_runs_strategy_name", table_name="paper_runs")
    op.drop_index("ix_paper_runs_account_id", table_name="paper_runs")
    op.drop_table("paper_runs")

    op.drop_index("ix_paper_positions_symbol", table_name="paper_positions")
    op.drop_index("ix_paper_positions_instrument_id", table_name="paper_positions")
    op.drop_index("ix_paper_positions_account_id", table_name="paper_positions")
    op.drop_table("paper_positions")

    op.drop_index("ix_market_bars_timestamp", table_name="market_bars")
    op.drop_index("ix_market_bars_instrument_id", table_name="market_bars")
    op.drop_table("market_bars")

    op.drop_index("ix_backtest_orders_run_id", table_name="backtest_orders")
    op.drop_table("backtest_orders")

    op.drop_index("ix_backtest_fills_run_id", table_name="backtest_fills")
    op.drop_table("backtest_fills")

    op.drop_index("ix_backtest_equity_points_timestamp", table_name="backtest_equity_points")
    op.drop_index("ix_backtest_equity_points_run_id", table_name="backtest_equity_points")
    op.drop_table("backtest_equity_points")

    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_command_name", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_table("paper_accounts")

    op.drop_index("ix_instruments_symbol", table_name="instruments")
    op.drop_index("ix_instruments_market", table_name="instruments")
    op.drop_table("instruments")

    op.drop_index("ix_backtest_runs_symbol", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_strategy_name", table_name="backtest_runs")
    op.drop_table("backtest_runs")
