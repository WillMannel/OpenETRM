import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import Commodity, CurveMethod, CurveStatus, MarketDataSource
from app.db.base import Base


class MarketDataPoint(Base):
    """Raw input quotes. `quote_date` is the Timescale hypertable time dimension --
    see alembic/versions for the `create_hypertable` call made against this table.

    Note: the migration gives this table a composite (id, quote_date) primary key at the
    DB level -- Timescale requires the partitioning column in any PK/unique constraint.
    The ORM mapping below only flags `id` as the primary key; that's fine for how this
    model is used today (insert + range queries, no `session.get()` by id), but keep it
    in mind if that changes.

    (commodity, quote_date, delivery_month) is this row's natural key --
    `uq_market_data_point_commodity_quote_delivery` enforces it at the DB level, a
    backstop behind MarketDataService.add_quote's proactive check-before-insert (which
    on its own would still have a check-then-act race between two concurrent
    submissions of the same quote; the DB constraint is what actually closes that).
    See ARCHITECTURE.md's "Risk reproducibility and lineage" section for why a
    duplicate isn't safe to allow at all: which of two same-day quotes "the"
    historical price window picks would otherwise be order-dependent.
    """

    __tablename__ = "market_data_points"
    __table_args__ = (
        UniqueConstraint(
            "commodity",
            "quote_date",
            "delivery_month",
            name="uq_market_data_point_commodity_quote_delivery",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_month: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    source: Mapped[MarketDataSource] = mapped_column(
        String(10), nullable=False, default=MarketDataSource.SEED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForwardCurve(Base):
    __tablename__ = "forward_curves"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    build_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    method: Mapped[CurveMethod] = mapped_column(
        String(30), nullable=False, default=CurveMethod.PIECEWISE_FLAT_MONTHLY
    )
    status: Mapped[CurveStatus] = mapped_column(
        String(10), nullable=False, default=CurveStatus.DRAFT
    )

    points: Mapped[list["CurvePoint"]] = relationship(
        back_populates="curve", order_by="CurvePoint.delivery_month", lazy="selectin"
    )


class CurvePoint(Base):
    __tablename__ = "curve_points"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    curve_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forward_curves.id"), nullable=False)
    curve: Mapped["ForwardCurve"] = relationship(back_populates="points")
    delivery_month: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    tenor_bucket: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
