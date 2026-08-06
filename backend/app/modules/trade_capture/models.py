import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import BuySell, Commodity, Currency, TradeStatus, TradeType, VolumeUnit
from app.db.base import Base


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    external_code: Mapped[str | None] = mapped_column(String(50))


class Book(Base):
    __tablename__ = "books"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(500))


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)

    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("counterparties.id"), nullable=False
    )
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    counterparty: Mapped["Counterparty"] = relationship(lazy="joined")
    book: Mapped["Book"] = relationship(lazy="joined")

    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    trade_type: Mapped[TradeType] = mapped_column(String(20), nullable=False)
    buy_sell: Mapped[BuySell] = mapped_column(String(10), nullable=False)

    volume: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    volume_unit: Mapped[VolumeUnit] = mapped_column(
        String(10), nullable=False, default=VolumeUnit.MMBTU
    )

    fixed_price: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    price_currency: Mapped[Currency] = mapped_column(
        String(5), nullable=False, default=Currency.USD
    )

    delivery_start_month: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_end_month: Mapped[date] = mapped_column(Date, nullable=False)

    floating_index: Mapped[str] = mapped_column(
        String(50), nullable=False, default="HENRY_HUB_PENULTIMATE"
    )
    status: Mapped[TradeStatus] = mapped_column(String(20), nullable=False, default=TradeStatus.NEW)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
