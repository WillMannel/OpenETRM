import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.common.enums import Commodity, Currency


class PositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    book_id: uuid.UUID
    commodity: Commodity
    delivery_month: date
    net_volume: float
    avg_fixed_price: float
    as_of_date: date


class ValuationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    trade_id: uuid.UUID | None
    book_id: uuid.UUID | None
    as_of_date: date
    curve_id: uuid.UUID
    mtm_value: float
    realized_pnl: float
    unrealized_pnl: float
    currency: Currency
    computed_at: datetime


class BookPnlSummary(BaseModel):
    book_id: uuid.UUID
    as_of_date: date
    total_mtm_value: float
    total_unrealized_pnl: float
    positions: list[PositionRead]
