import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VarResult(Base):
    __tablename__ = "var_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("books.id"), nullable=True
    )  # null = whole portfolio
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    confidence_level: Mapped[int] = mapped_column(Integer, nullable=False)  # 95 | 99
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="HISTORICAL_SIM")
    scenario_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=250)
    # Decimal: this is the persisted, reportable dollar VaR number -- the
    # historical-sim/parametric/Monte Carlo *computation* that produces it stays
    # float/numpy internally (see app.modules.risk.var), only the boundary where the
    # result is written here goes through app.common.money.to_decimal.
    var_value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SensitivityResult(Base):
    __tablename__ = "sensitivity_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    curve_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forward_curves.id"), nullable=False)
    tenor_bucket: Mapped[str] = mapped_column(String(7), nullable=False)
    delta_value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    # float, deliberately: the size of the price bump used to compute delta_value is a
    # quant model input, not a persisted money amount.
    bump_size: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
