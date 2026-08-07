"""initial schema: trade capture, market data/curves, valuation, risk

Revision ID: 10aaf6d5f899
Revises:
Create Date: 2026-08-06

Table shapes here mirror app/modules/*/models.py exactly (verified by compiling each
table's CreateTable DDL against the postgres dialect before writing this migration).
The one thing beyond a straight schema translation is turning `market_data_points`
into a TimescaleDB hypertable on `quote_date` -- that's not something the SQLAlchemy
model layer expresses, so it's done here as raw SQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "10aaf6d5f899"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "counterparties",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("external_code", sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "books",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "forward_curves",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("commodity", sa.String(30), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column(
            "build_timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("method", sa.String(30), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forward_curves_commodity_as_of_date", "forward_curves", ["commodity", "as_of_date"])

    op.create_table(
        "trades",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("counterparty_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("commodity", sa.String(30), nullable=False),
        sa.Column("trade_type", sa.String(20), nullable=False),
        sa.Column("buy_sell", sa.String(10), nullable=False),
        sa.Column("volume", sa.Numeric(18, 4), nullable=False),
        sa.Column("volume_unit", sa.String(10), nullable=False),
        sa.Column("fixed_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("price_currency", sa.String(5), nullable=False),
        sa.Column("delivery_start_month", sa.Date(), nullable=False),
        sa.Column("delivery_end_month", sa.Date(), nullable=False),
        sa.Column("floating_index", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["counterparty_id"], ["counterparties.id"]),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_book_id", "trades", ["book_id"])

    op.create_table(
        "market_data_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("commodity", sa.String(30), nullable=False),
        sa.Column("quote_date", sa.Date(), nullable=False),
        sa.Column("delivery_month", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(18, 6), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", "quote_date"),  # hypertables require the time column in the PK
    )
    op.create_index(
        "ix_market_data_points_commodity_month", "market_data_points", ["commodity", "delivery_month"]
    )

    op.create_table(
        "curve_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("curve_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_month", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(18, 6), nullable=False),
        sa.Column("tenor_bucket", sa.String(7), nullable=False),
        sa.ForeignKeyConstraint(["curve_id"], ["forward_curves.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_curve_points_curve_id", "curve_points", ["curve_id"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("commodity", sa.String(30), nullable=False),
        sa.Column("delivery_month", sa.Date(), nullable=False),
        sa.Column("net_volume", sa.Numeric(18, 4), nullable=False),
        sa.Column("avg_fixed_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "valuation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=True),
        sa.Column("book_id", sa.Uuid(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("curve_id", sa.Uuid(), nullable=False),
        sa.Column("mtm_value", sa.Numeric(20, 6), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(20, 6), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(5), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"]),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["curve_id"], ["forward_curves.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_valuation_results_book_as_of", "valuation_results", ["book_id", "as_of_date"])

    op.create_table(
        "var_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("confidence_level", sa.Integer(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("scenario_window_days", sa.Integer(), nullable=False),
        sa.Column("var_value", sa.Numeric(20, 6), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "sensitivity_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("curve_id", sa.Uuid(), nullable=False),
        sa.Column("tenor_bucket", sa.String(7), nullable=False),
        sa.Column("delta_value", sa.Numeric(20, 6), nullable=False),
        sa.Column("bump_size", sa.Numeric(10, 6), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["curve_id"], ["forward_curves.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # TimescaleDB: turn market_data_points into a hypertable partitioned on quote_date.
    # No-ops (rather than failing) if the extension isn't present, so this migration
    # still works against a plain Postgres instance in dev/test if someone runs it there.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute(
        "SELECT create_hypertable('market_data_points', 'quote_date', if_not_exists => TRUE, "
        "migrate_data => TRUE)"
    )


def downgrade() -> None:
    op.drop_table("sensitivity_results")
    op.drop_table("var_results")
    op.drop_table("valuation_results")
    op.drop_table("positions")
    op.drop_table("curve_points")
    op.drop_table("market_data_points")
    op.drop_table("trades")
    op.drop_table("forward_curves")
    op.drop_table("books")
    op.drop_table("counterparties")
