import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Desk(Base):
    """A trading desk: purely organizational grouping in v1 (name only), but also the
    thing that turns on book-level entitlement enforcement -- see Book.desk_id and
    app.modules.entitlements.service.EntitlementService for why a book without a desk
    is unrestricted."""

    __tablename__ = "desks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(500))


class BookMembership(Base):
    """An explicit grant: `user_id` may see/act on `book_id`. This is the only
    enforcement primitive in v1 -- there is no desk-wide "every member of this desk
    gets every book under it" grant yet (see FUTURE_WORK.md); each book that opts into
    enforcement (by being assigned a desk_id) needs its own membership rows per user."""

    __tablename__ = "book_memberships"
    __table_args__ = (UniqueConstraint("book_id", "user_id", name="uq_book_membership"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
