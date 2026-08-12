"""risk reproducibility and lineage

Revision ID: e5b8f3a291c7
Revises: d4a7f21b8c93
Create Date: 2026-08-12

Adds lineage columns (trade_ids_used, code_version) to valuation_runs,
var_results, sensitivity_results -- the exact set of live Trade ids that fed a
computation, and the app.common.lineage.get_code_version() value at computation
time. var_results also gains commodity (previously absent entirely) and
market_data_point_ids (the exact MarketDataPoint ids that composed its price
panel). valuation_results gains risk_free_rate_used (only set for per-trade
OPTION rows). Creates stress_results and option_greeks_results -- both were
previously computed and returned but never persisted, leaving zero DB trace that
a stress test or a greeks run ever happened. Adds a uniqueness constraint on
market_data_points(commodity, quote_date, delivery_month) to close a determinism
gap: without it, two quotes for the same day/month made "the" historical price
window order-dependent, not reproducible. See ARCHITECTURE.md's "Risk
reproducibility and lineage" section for the full design.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b8f3a291c7"
down_revision: str | None = "d4a7f21b8c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON()


def upgrade() -> None:
    op.add_column("valuation_runs", sa.Column("trade_ids_used", _JSON, nullable=True))
    op.add_column("valuation_runs", sa.Column("code_version", sa.String(100), nullable=True))

    op.add_column(
        "valuation_results", sa.Column("risk_free_rate_used", sa.Numeric(10, 6), nullable=True)
    )

    op.add_column("var_results", sa.Column("commodity", sa.String(30), nullable=True))
    op.add_column("var_results", sa.Column("trade_ids_used", _JSON, nullable=True))
    op.add_column("var_results", sa.Column("market_data_point_ids", _JSON, nullable=True))
    op.add_column("var_results", sa.Column("code_version", sa.String(100), nullable=True))

    op.add_column("sensitivity_results", sa.Column("trade_ids_used", _JSON, nullable=True))
    op.add_column("sensitivity_results", sa.Column("code_version", sa.String(100), nullable=True))

    op.create_table(
        "stress_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("commodity", sa.String(30), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("curve_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_name", sa.String(100), nullable=False),
        sa.Column("shock_type", sa.String(10), nullable=False),
        sa.Column("shock_value", sa.Numeric(10, 6), nullable=False),
        sa.Column("pnl_impact", sa.Numeric(20, 6), nullable=False),
        sa.Column("trade_ids_used", _JSON, nullable=True),
        sa.Column("code_version", sa.String(100), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["curve_id"], ["forward_curves.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stress_results_book_id", "stress_results", ["book_id"])

    op.create_table(
        "option_greeks_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("commodity", sa.String(30), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("curve_id", sa.Uuid(), nullable=False),
        sa.Column("delta", sa.Numeric(18, 8), nullable=False),
        sa.Column("gamma", sa.Numeric(18, 8), nullable=False),
        sa.Column("vega", sa.Numeric(18, 8), nullable=False),
        sa.Column("theta", sa.Numeric(18, 8), nullable=False),
        sa.Column("risk_free_rate_used", sa.Numeric(10, 6), nullable=False),
        sa.Column("code_version", sa.String(100), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"]),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["curve_id"], ["forward_curves.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_option_greeks_results_trade_id", "option_greeks_results", ["trade_id"])
    op.create_index("ix_option_greeks_results_book_id", "option_greeks_results", ["book_id"])

    # Timescale requires the hypertable's partitioning column (quote_date) in any
    # unique constraint -- already satisfied here since it's part of the key.
    op.create_unique_constraint(
        "uq_market_data_point_commodity_quote_delivery",
        "market_data_points",
        ["commodity", "quote_date", "delivery_month"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_market_data_point_commodity_quote_delivery", "market_data_points", type_="unique"
    )

    op.drop_index("ix_option_greeks_results_book_id", table_name="option_greeks_results")
    op.drop_index("ix_option_greeks_results_trade_id", table_name="option_greeks_results")
    op.drop_table("option_greeks_results")

    op.drop_index("ix_stress_results_book_id", table_name="stress_results")
    op.drop_table("stress_results")

    op.drop_column("sensitivity_results", "code_version")
    op.drop_column("sensitivity_results", "trade_ids_used")

    op.drop_column("var_results", "code_version")
    op.drop_column("var_results", "market_data_point_ids")
    op.drop_column("var_results", "trade_ids_used")
    op.drop_column("var_results", "commodity")

    op.drop_column("valuation_results", "risk_free_rate_used")

    op.drop_column("valuation_runs", "code_version")
    op.drop_column("valuation_runs", "trade_ids_used")
