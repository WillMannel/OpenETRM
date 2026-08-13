"""valuation runs: separate computation from persistence, idempotent reads

Revision ID: b4f9c2a81e07
Revises: a7c2e9f14d68
Create Date: 2026-08-12

Adds `valuation_runs`, the entity `positions`/`valuation_results` rows now attach to
via `run_id`. Before this migration, GET /positions/{book_id}/pnl computed AND
persisted on every call -- three identical GETs produced three duplicate rows for the
same snapshot (proven in tests/integration/test_valuation_run_idempotency.py). Now
that read endpoint is a pure computation with no DB writes; a new, explicit
POST /positions/{book_id}/valuation-runs is the only thing that persists, and it
always creates a fresh ValuationRun rather than mutating a prior one.

`run_id` on positions/valuation_results is nullable, and the new commodity/
delivery_month columns on valuation_results are nullable too -- there's no
backward-incompatible NOT NULL added here (matching the pattern already used for the
option-trade columns in 9d3a7e2c5f81): any pre-existing row from before this migration
simply won't participate in the run-scoped uniqueness or the "latest run" view/export
filters, which is the correct behavior for data that predates the run concept.

v_positions_flat and v_valuation_results_flat are dropped and recreated to join
through valuation_runs and select only the latest run per (book, commodity,
as_of_date) -- see the reporting_views migration this supersedes for the pre-run-scoped
versions.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4f9c2a81e07"
down_revision: str | None = "a7c2e9f14d68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRE_RUN_VIEWS: dict[str, str] = {
    "v_positions_flat": """
        SELECT
            p.id,
            b.name AS book_name,
            p.commodity,
            p.delivery_month,
            p.net_volume,
            p.avg_fixed_price,
            p.as_of_date
        FROM positions p
        JOIN books b ON b.id = p.book_id
    """,
    "v_valuation_results_flat": """
        SELECT
            v.id,
            v.trade_id,
            b.name AS book_name,
            v.as_of_date,
            v.mtm_value,
            v.realized_pnl,
            v.unrealized_pnl,
            v.currency,
            v.computed_at
        FROM valuation_results v
        LEFT JOIN books b ON b.id = v.book_id
    """,
}

# DISTINCT ON (book_id, commodity, as_of_date) ... ORDER BY ... computed_at DESC is
# the Postgres idiom for "one row per group, the newest". `computed_at` is set
# client-side in Python (microsecond resolution) rather than left to the DB's `now()`
# -- see ValuationRun's docstring for why that matters here. These views only ever run
# against Postgres (see backend-integration-postgres CI job; SQLite tests build the
# schema via Base.metadata.create_all, never these Alembic-only views).
_LATEST_RUN_VIEWS: dict[str, str] = {
    "v_positions_flat": """
        SELECT
            p.id,
            b.name AS book_name,
            p.commodity,
            p.delivery_month,
            p.net_volume,
            p.avg_fixed_price,
            p.as_of_date,
            p.run_id
        FROM positions p
        JOIN books b ON b.id = p.book_id
        WHERE p.run_id IN (
            SELECT DISTINCT ON (r.book_id, r.commodity, r.as_of_date) r.id
            FROM valuation_runs r
            ORDER BY r.book_id, r.commodity, r.as_of_date, r.computed_at DESC
        )
    """,
    "v_valuation_results_flat": """
        SELECT
            v.id,
            v.trade_id,
            b.name AS book_name,
            v.commodity,
            v.delivery_month,
            v.as_of_date,
            v.mtm_value,
            v.realized_pnl,
            v.unrealized_pnl,
            v.currency,
            v.computed_at,
            v.run_id
        FROM valuation_results v
        LEFT JOIN books b ON b.id = v.book_id
        WHERE v.run_id IN (
            SELECT DISTINCT ON (r.book_id, r.commodity, r.as_of_date) r.id
            FROM valuation_runs r
            ORDER BY r.book_id, r.commodity, r.as_of_date, r.computed_at DESC
        )
    """,
}


def upgrade() -> None:
    for view in _PRE_RUN_VIEWS:
        op.execute(f"DROP VIEW {view}")

    op.create_table(
        "valuation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("commodity", sa.String(30), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("curve_id", sa.Uuid(), nullable=False),
        sa.Column("computed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["curve_id"], ["forward_curves.id"]),
        sa.ForeignKeyConstraint(["computed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_valuation_runs_book_commodity_as_of",
        "valuation_runs",
        ["book_id", "commodity", "as_of_date"],
    )

    op.add_column("positions", sa.Column("run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_positions_run_id", "positions", "valuation_runs", ["run_id"], ["id"])
    op.create_unique_constraint(
        "uq_position_run_grain", "positions", ["run_id", "book_id", "commodity", "delivery_month"]
    )

    op.add_column("valuation_results", sa.Column("run_id", sa.Uuid(), nullable=True))
    op.add_column("valuation_results", sa.Column("commodity", sa.String(30), nullable=True))
    op.add_column("valuation_results", sa.Column("delivery_month", sa.Date(), nullable=True))
    op.create_foreign_key(
        "fk_valuation_results_run_id", "valuation_results", "valuation_runs", ["run_id"], ["id"]
    )
    op.create_index(
        "uq_valuation_result_run_book_leg",
        "valuation_results",
        ["run_id", "book_id", "commodity", "delivery_month"],
        unique=True,
        postgresql_where=sa.text("trade_id IS NULL"),
    )
    op.create_index(
        "uq_valuation_result_run_trade",
        "valuation_results",
        ["run_id", "trade_id"],
        unique=True,
        postgresql_where=sa.text("trade_id IS NOT NULL"),
    )

    for name, query in _LATEST_RUN_VIEWS.items():
        op.execute(f"CREATE VIEW {name} AS{query}")


def downgrade() -> None:
    for view in _LATEST_RUN_VIEWS:
        op.execute(f"DROP VIEW {view}")

    op.drop_index("uq_valuation_result_run_trade", table_name="valuation_results")
    op.drop_index("uq_valuation_result_run_book_leg", table_name="valuation_results")
    op.drop_constraint("fk_valuation_results_run_id", "valuation_results", type_="foreignkey")
    op.drop_column("valuation_results", "delivery_month")
    op.drop_column("valuation_results", "commodity")
    op.drop_column("valuation_results", "run_id")

    op.drop_constraint("uq_position_run_grain", "positions", type_="unique")
    op.drop_constraint("fk_positions_run_id", "positions", type_="foreignkey")
    op.drop_column("positions", "run_id")

    op.drop_index("ix_valuation_runs_book_commodity_as_of", table_name="valuation_runs")
    op.drop_table("valuation_runs")

    for name, query in _PRE_RUN_VIEWS.items():
        op.execute(f"CREATE VIEW {name} AS{query}")
