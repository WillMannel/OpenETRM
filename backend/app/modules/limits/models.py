import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import Commodity, LimitBreachStatus, LimitType
from app.db.base import Base


class BookLimit(Base):
    """A risk limit attached to a book+commodity. VOLUME limits compare against the
    largest absolute net volume across any delivery month; VAR limits compare against
    the most recent VaR run at `confidence_level`. Only one limit of each type may exist
    per (book, commodity) -- update the existing row rather than stacking duplicates."""

    __tablename__ = "book_limits"
    __table_args__ = (UniqueConstraint("book_id", "commodity", "limit_type", name="uq_book_limit"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    limit_type: Mapped[LimitType] = mapped_column(String(10), nullable=False)
    threshold: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Only meaningful for VAR limits; ignored for VOLUME.
    confidence_level: Mapped[int] = mapped_column(nullable=False, default=95)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LimitBreach(Base):
    """A point-in-time record that a book's observed exposure exceeded its configured
    limit. Breaches are never blocking by themselves for VAR limits (informational --
    the risk run still returns); VOLUME limits are enforced pre-trade at confirm time,
    so a VOLUME breach row records a rejected confirm attempt, not a live position."""

    __tablename__ = "limit_breaches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    limit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("book_limits.id"), nullable=False)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    limit_type: Mapped[LimitType] = mapped_column(String(10), nullable=False)
    threshold: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    observed_value: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[LimitBreachStatus] = mapped_column(
        String(20), nullable=False, default=LimitBreachStatus.OPEN
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
