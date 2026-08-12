import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import Commodity
from app.db.base import Base

_JSON = JSON().with_variant(JSONB, "postgresql")

# Lineage columns repeated across every persisted risk/valuation result -- see
# ARCHITECTURE.md's "Risk reproducibility and lineage" section. `trade_ids_used` is
# the exact set of `Trade.id`s live at computation time that fed the number (proving,
# after the fact, exactly which trades produced it, independent of whatever's live
# *now*); `code_version` is `app.common.lineage.get_code_version()`'s value at
# computation time. Both nullable: rows written before this column existed have
# neither, and there's no way to reconstruct either retroactively -- nullable is
# honest about that, not a design choice to leave them optional going forward.


class VarResult(Base):
    __tablename__ = "var_results"
    # Previously had no supporting index at all beyond the PK -- a book-scoped
    # history query (ExportService.var_results, or any future "VaR over time for
    # this book" view) sequential-scanned the whole table. See task P1-9,
    # ARCHITECTURE.md's "Scale and performance".
    __table_args__ = (Index("ix_var_results_book_id", "book_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("books.id"), nullable=True
    )  # null = whole portfolio
    # Added alongside the lineage columns below -- VarResult previously had no
    # commodity column at all, so a result couldn't even self-report which
    # commodity's positions/quotes it was computed from.
    commodity: Mapped[Commodity | None] = mapped_column(String(30), nullable=True)
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
    trade_ids_used: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)
    # The exact MarketDataPoint.id set that composed the price-history panel --
    # without this, a later-arriving/backdated quote insert into the same historical
    # window would silently change what "re-running this VaR" sees, with no way to
    # detect it happened (see ARCHITECTURE.md).
    market_data_point_ids: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SensitivityResult(Base):
    __tablename__ = "sensitivity_results"
    __table_args__ = (Index("ix_sensitivity_results_book_id", "book_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    curve_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forward_curves.id"), nullable=False)
    tenor_bucket: Mapped[str] = mapped_column(String(7), nullable=False)
    delta_value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    # float, deliberately: the size of the price bump used to compute delta_value is a
    # quant model input, not a persisted money amount.
    bump_size: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    trade_ids_used: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StressResult(Base):
    """A persisted stress-test scenario result -- previously an ephemeral response
    object with zero database trace (see ARCHITECTURE.md): a stress test could be run
    and its result shown to a risk manager with no way to later prove it ever
    happened, let alone what data produced it."""

    __tablename__ = "stress_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    curve_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forward_curves.id"), nullable=False)
    scenario_name: Mapped[str] = mapped_column(String(100), nullable=False)
    shock_type: Mapped[str] = mapped_column(String(10), nullable=False)
    shock_value: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    pnl_impact: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    trade_ids_used: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OptionGreeksResult(Base):
    """A persisted per-trade Black-76 greeks result -- same "previously ephemeral,
    zero DB trace" gap as StressResult, plus (uniquely to option pricing) a
    risk-free rate read from a single global config default
    (`Settings.risk_free_rate`) at computation time and never otherwise recorded --
    `risk_free_rate_used` closes that: if the rate is ever changed, every result
    computed under the old rate remains provably attributable to it, rather than
    silently becoming unreproducible from stored data."""

    __tablename__ = "option_greeks_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trade_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trades.id"), nullable=False)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    curve_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forward_curves.id"), nullable=False)
    delta: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    gamma: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    vega: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    theta: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    risk_free_rate_used: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    code_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
