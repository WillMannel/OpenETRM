import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.common.enums import Commodity, Currency
from app.common.money import MoneyDecimal


class PositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    book_id: uuid.UUID
    commodity: Commodity
    delivery_month: date
    net_volume: MoneyDecimal
    avg_fixed_price: MoneyDecimal
    as_of_date: date


class ValuationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    trade_id: uuid.UUID | None
    book_id: uuid.UUID | None
    as_of_date: date
    curve_id: uuid.UUID
    mtm_value: MoneyDecimal
    realized_pnl: MoneyDecimal
    unrealized_pnl: MoneyDecimal
    currency: Currency
    # Only set for a per-trade OPTION result -- see ValuationResult.risk_free_rate_used.
    risk_free_rate_used: MoneyDecimal | None = None
    computed_at: datetime


class BookPnlSummary(BaseModel):
    book_id: uuid.UUID
    as_of_date: date
    total_mtm_value: MoneyDecimal
    total_unrealized_pnl: MoneyDecimal
    positions: list[PositionRead]


class ValuationRunCreate(BaseModel):
    as_of_date: date
    commodity: Commodity = Commodity.HENRY_HUB


class ValuationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID
    commodity: Commodity
    as_of_date: date
    curve_id: uuid.UUID
    computed_by_user_id: uuid.UUID | None
    # Lineage (see ARCHITECTURE.md's "Risk reproducibility and lineage"): the exact
    # Trade.id's live at computation time, and the code version that computed this
    # run. Null for rows written before these columns existed.
    trade_ids_used: list[str] | None = None
    code_version: str | None = None
    computed_at: datetime


class ValuationRunSummary(BaseModel):
    """The persisted counterpart of BookPnlSummary -- returned by the write endpoint
    that creates a new ValuationRun, so the caller sees the same numbers GET /pnl would
    have shown, plus the run's identity for audit/lineage."""

    run: ValuationRunRead
    total_mtm_value: MoneyDecimal
    total_unrealized_pnl: MoneyDecimal
    positions: list[PositionRead]
    results: list[ValuationResultRead]
