import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import Commodity, Currency
from app.db.base import Base


class Position(Base):
    """A net-volume rollup by book/delivery-month, recomputed on each valuation run --
    not an independently-mutated ledger."""

    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    delivery_month: Mapped[date] = mapped_column(Date, nullable=False)
    net_volume: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    avg_fixed_price: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)


class ValuationResult(Base):
    __tablename__ = "valuation_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trade_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trades.id"), nullable=True)
    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("books.id"), nullable=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    curve_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forward_curves.id"), nullable=False)
    mtm_value: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[Currency] = mapped_column(String(5), nullable=False, default=Currency.USD)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
