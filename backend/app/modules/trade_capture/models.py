import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import (
    BuySell,
    ChangeRequestStatus,
    ChangeRequestType,
    Commodity,
    Currency,
    OptionType,
    PowerBlock,
    TradeStatus,
    TradeType,
    VolumeUnit,
)
from app.db.base import Base

_JSON = JSON().with_variant(JSONB, "postgresql")


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
    # NULL = unrestricted (any authenticated user with the right role may access this
    # book, today's behavior). Setting this turns on entitlement enforcement -- only
    # ADMIN or a user with a BookMembership for this book may access it from then on.
    # See app.modules.entitlements for the full design rationale.
    desk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("desks.id"), nullable=True)


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

    # Null for OPTION trades (priced off strike_price/premium/option_volatility instead).
    fixed_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_currency: Mapped[Currency] = mapped_column(
        String(5), nullable=False, default=Currency.USD
    )

    delivery_start_month: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_end_month: Mapped[date] = mapped_column(Date, nullable=False)

    floating_index: Mapped[str] = mapped_column(
        String(50), nullable=False, default="HENRY_HUB_PENULTIMATE"
    )

    # Populated only for trade_type=OPTION; null for SWAP/FORWARD. See
    # app.modules.valuation.options for the Black-76 pricer these feed.
    option_type: Mapped[OptionType | None] = mapped_column(String(10), nullable=True)
    strike_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    premium: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    option_volatility: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    # Populated only for commodity=POWER; null otherwise. See common.enums.PowerBlock.
    power_block: Mapped[PowerBlock | None] = mapped_column(String(10), nullable=True)

    # Populated only for trade_type in (REC, EMISSIONS_ALLOWANCE); null otherwise.
    # certificate_registry is free text (e.g. "WREGIS", "NEPOOL-GIS", "PJM-GATS", "RGGI") rather
    # than an enum -- which registries/programs matter is deployment-specific and
    # growing the list shouldn't need a migration.
    certificate_registry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vintage_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[TradeStatus] = mapped_column(String(20), nullable=False, default=TradeStatus.NEW)

    # Lifecycle/versioning: an approved amendment creates a *new* Trade row (this one
    # gets marked AMENDED) rather than mutating in place, so the audit log and any past
    # valuation/risk runs still refer to the exact terms that were live at the time.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trades.id"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TradeChangeRequest(Base):
    """A proposed amendment or cancellation, pending four-eyes approval. The requester
    and the approver must be different users (enforced in the service layer, not here)."""

    __tablename__ = "trade_change_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trade_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trades.id"), nullable=False)
    change_type: Mapped[ChangeRequestType] = mapped_column(String(20), nullable=False)
    status: Mapped[ChangeRequestStatus] = mapped_column(
        String(20), nullable=False, default=ChangeRequestStatus.PENDING
    )

    # For AMENDMENT: a partial dict of {field: new_value} to apply on approval.
    # For CANCELLATION: null.
    proposed_changes: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)

    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
