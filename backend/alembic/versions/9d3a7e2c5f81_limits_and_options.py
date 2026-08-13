"""position/trading limits and option trade support

Revision ID: 9d3a7e2c5f81
Revises: 6f2a1c9d4b3e
Create Date: 2026-08-07

Adds: book_limits, limit_breaches tables; option_type/strike_price/premium/
option_volatility columns on trades; relaxes trades.fixed_price to nullable (it's
required for SWAP/FORWARD but must be null for OPTION, which is priced off
strike_price/premium/option_volatility instead -- enforced at the schema/service
layer, not the DB). Table shapes verified the same way as prior migrations: compiling
each table's CreateTable DDL against the postgres dialect offline before writing this
by hand.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d3a7e2c5f81"
down_revision: str | None = "6f2a1c9d4b3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("trades", "fixed_price", existing_type=sa.Numeric(18, 6), nullable=True)
    op.add_column("trades", sa.Column("option_type", sa.String(10), nullable=True))
    op.add_column("trades", sa.Column("strike_price", sa.Numeric(18, 6), nullable=True))
    op.add_column("trades", sa.Column("premium", sa.Numeric(18, 6), nullable=True))
    op.add_column("trades", sa.Column("option_volatility", sa.Numeric(9, 6), nullable=True))

    op.create_table(
        "book_limits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("commodity", sa.String(30), nullable=False),
        sa.Column("limit_type", sa.String(10), nullable=False),
        sa.Column("threshold", sa.Numeric(20, 6), nullable=False),
        sa.Column("confidence_level", sa.Integer(), server_default="95", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "commodity", "limit_type", name="uq_book_limit"),
    )

    op.create_table(
        "limit_breaches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("limit_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("commodity", sa.String(30), nullable=False),
        sa.Column("limit_type", sa.String(10), nullable=False),
        sa.Column("threshold", sa.Numeric(20, 6), nullable=False),
        sa.Column("observed_value", sa.Numeric(20, 6), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("acknowledged_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["limit_id"], ["book_limits.id"]),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_limit_breaches_status", "limit_breaches", ["status"])


def downgrade() -> None:
    op.drop_index("ix_limit_breaches_status", table_name="limit_breaches")
    op.drop_table("limit_breaches")
    op.drop_table("book_limits")
    op.drop_column("trades", "option_volatility")
    op.drop_column("trades", "premium")
    op.drop_column("trades", "strike_price")
    op.drop_column("trades", "option_type")
    op.alter_column("trades", "fixed_price", existing_type=sa.Numeric(18, 6), nullable=False)
