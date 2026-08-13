"""scale and performance indexes

Revision ID: f9a3c7e18b52
Revises: e5b8f3a291c7
Create Date: 2026-08-12

Adds indexes for hot-path queries that had no supporting index at any realistic
scale (found by task P1-9's index audit -- see ARCHITECTURE.md's "Scale and
performance" section):

- trades: TradeRepository.list_live's two real call shapes (a single book scoped
  to a commodity, or a portfolio-wide risk run scoped to a commodity -- every
  caller always passes a specific commodity) were only partially served by the
  old book_id-only index, and not at all for the portfolio-wide case. Trade
  amendments never mutate a row in place (a new Trade row is created, the old one
  marked AMENDED -- see Trade.version/previous_version_id), so superseded rows
  accumulate forever and the live fraction of any index scan shrinks over time.
- var_results, sensitivity_results: no book_id index at all (sensitivity_results'
  sibling tables stress_results/option_greeks_results already got one when they
  were created in e5b8f3a291c7 -- this was a straightforward oversight to fix).
- limit_breaches: the pre-existing status-only index left book_id unindexed, so a
  book-scoped open-breaches lookup still filtered every OPEN row globally.

All purely additive (no drops) -- the old single-column indexes these make
partially redundant (e.g. trades' book_id-only index) are left in place rather
than removed, to keep this migration's downgrade path simple and its risk low.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f9a3c7e18b52"
down_revision: str | None = "e5b8f3a291c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_trades_book_id_commodity_status", "trades", ["book_id", "commodity", "status"]
    )
    op.create_index("ix_trades_commodity_status", "trades", ["commodity", "status"])
    op.create_index("ix_var_results_book_id", "var_results", ["book_id"])
    op.create_index("ix_sensitivity_results_book_id", "sensitivity_results", ["book_id"])
    op.create_index("ix_limit_breaches_status_book_id", "limit_breaches", ["status", "book_id"])


def downgrade() -> None:
    op.drop_index("ix_limit_breaches_status_book_id", table_name="limit_breaches")
    op.drop_index("ix_sensitivity_results_book_id", table_name="sensitivity_results")
    op.drop_index("ix_var_results_book_id", table_name="var_results")
    op.drop_index("ix_trades_commodity_status", table_name="trades")
    op.drop_index("ix_trades_book_id_commodity_status", table_name="trades")
