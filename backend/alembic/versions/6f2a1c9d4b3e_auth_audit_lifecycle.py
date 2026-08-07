"""auth, audit log, and trade lifecycle (versioning + four-eyes change requests)

Revision ID: 6f2a1c9d4b3e
Revises: 10aaf6d5f899
Create Date: 2026-08-06

Adds: users, audit_log, trade_change_requests tables, and three new columns on
trades (version, previous_version_id, created_by_user_id). Table shapes verified the
same way as the initial migration: compiling each table's CreateTable DDL against the
postgres dialect offline before writing this by hand.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f2a1c9d4b3e"
down_revision: str | None = "10aaf6d5f899"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("before", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True),
        sa.Column("after", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])

    op.create_table(
        "trade_change_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("change_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("proposed_changes", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(1000), nullable=True),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trade_change_requests_status", "trade_change_requests", ["status"])

    op.add_column("trades", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("trades", sa.Column("previous_version_id", sa.Uuid(), nullable=True))
    op.add_column("trades", sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_trades_previous_version_id_trades", "trades", "trades", ["previous_version_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_trades_created_by_user_id_users", "trades", "users", ["created_by_user_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_trades_created_by_user_id_users", "trades", type_="foreignkey")
    op.drop_constraint("fk_trades_previous_version_id_trades", "trades", type_="foreignkey")
    op.drop_column("trades", "created_by_user_id")
    op.drop_column("trades", "previous_version_id")
    op.drop_column("trades", "version")
    op.drop_table("trade_change_requests")
    op.drop_table("audit_log")
    op.drop_table("users")
