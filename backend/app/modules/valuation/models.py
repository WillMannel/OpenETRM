import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import Commodity, Currency
from app.db.base import Base


class ValuationRun(Base):
    """One explicit, persisted mark-to-market computation for a (book, commodity,
    as_of_date). This is the unit `Position`/`ValuationResult` rows attach to via
    `run_id` -- creating a run is a deliberate write action (see
    ValuationService.persist_valuation_run / POST /positions/{book_id}/valuation-runs),
    kept separate from the read path (GET /positions/{book_id}/pnl), which computes the
    same numbers on demand without writing anything. Before this entity existed, the
    read endpoint itself called session.add()/commit() on every call -- three identical
    GETs produced three duplicate Position/ValuationResult rows for the same snapshot
    (proven in tests/integration/test_valuation_run_idempotency.py). A book/commodity/
    as_of_date can have many runs over time (re-run after a late trade, a curve
    republish, an EOD close) -- reporting reads the latest one; see
    v_positions_flat/v_valuation_results_flat.

    `computed_at` is set client-side (`default=`), not left to the DB's `now()`
    (`server_default=` is still declared as a DDL-level fallback for rows inserted by
    something other than this ORM) -- SQLite's CURRENT_TIMESTAMP only has whole-second
    resolution, so two runs created in the same second (two back-to-back POSTs in a
    script, or in a test) would tie and make "the latest run" ambiguous. Python's clock
    gives microsecond resolution on every backend, which is what
    v_positions_flat/v_valuation_results_flat and ExportService's latest-run filter
    order by."""

    __tablename__ = "valuation_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    curve_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forward_curves.id"), nullable=False)
    computed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class Position(Base):
    """A net-volume rollup by book/commodity/delivery-month for one ValuationRun --
    recomputed fresh by each run, never mutated in place. `run_id` is nullable only to
    tolerate rows written before this column existed; every row created going forward
    always sets it (enforced by ValuationService.persist_valuation_run, not the DB)."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "book_id", "commodity", "delivery_month", name="uq_position_run_grain"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("valuation_runs.id"), nullable=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), nullable=False)
    commodity: Mapped[Commodity] = mapped_column(String(30), nullable=False)
    delivery_month: Mapped[date] = mapped_column(Date, nullable=False)
    net_volume: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    avg_fixed_price: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)


class ValuationResult(Base):
    """One valuation line -- either the aggregate result for a (commodity,
    delivery_month) linear position (`trade_id` null) or a per-trade OPTION result
    (`trade_id` set). `commodity`/`delivery_month`/`run_id` are nullable only to
    tolerate rows written before these columns existed; every row created going
    forward always sets them. Two partial unique indexes (below) enforce one row per
    logical value per run: one aggregate row per (run, book, commodity, month), and one
    row per (run, option trade) -- both scoped to `run_id`, so re-running never
    collides with a prior run's rows for the same book/commodity/month."""

    __tablename__ = "valuation_results"
    __table_args__ = (
        Index(
            "uq_valuation_result_run_book_leg",
            "run_id",
            "book_id",
            "commodity",
            "delivery_month",
            unique=True,
            postgresql_where=text("trade_id IS NULL"),
            sqlite_where=text("trade_id IS NULL"),
        ),
        Index(
            "uq_valuation_result_run_trade",
            "run_id",
            "trade_id",
            unique=True,
            postgresql_where=text("trade_id IS NOT NULL"),
            sqlite_where=text("trade_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("valuation_runs.id"), nullable=True)
    trade_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trades.id"), nullable=True)
    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("books.id"), nullable=True)
    commodity: Mapped[Commodity | None] = mapped_column(String(30), nullable=True)
    delivery_month: Mapped[date | None] = mapped_column(Date, nullable=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    curve_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forward_curves.id"), nullable=False)
    mtm_value: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[Currency] = mapped_column(String(5), nullable=False, default=Currency.USD)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
