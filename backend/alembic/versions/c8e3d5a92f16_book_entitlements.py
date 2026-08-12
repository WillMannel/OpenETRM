"""book-level entitlements: desks, book memberships, books.desk_id

Revision ID: c8e3d5a92f16
Revises: b4f9c2a81e07
Create Date: 2026-08-12

Adds `desks` and `book_memberships`, plus a nullable `desk_id` on `books`. A book with
no desk stays unrestricted (today's behavior: any authenticated user with the right
role may access it); assigning a book to a desk turns on entitlement enforcement --
from then on only ADMIN or a user with a `book_memberships` row for that book may
access it. See app.modules.entitlements.service.EntitlementService for the full design
rationale and app.modules.entitlements.models for the docstrings this migration mirrors.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e3d5a92f16"
down_revision: str | None = "b4f9c2a81e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "desks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.add_column("books", sa.Column("desk_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_books_desk_id", "books", "desks", ["desk_id"], ["id"])

    op.create_table(
        "book_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "user_id", name="uq_book_membership"),
    )
    op.create_index("ix_book_memberships_user_id", "book_memberships", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_book_memberships_user_id", table_name="book_memberships")
    op.drop_table("book_memberships")

    op.drop_constraint("fk_books_desk_id", "books", type_="foreignkey")
    op.drop_column("books", "desk_id")

    op.drop_table("desks")
