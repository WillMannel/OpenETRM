import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.common.enums import BuySell, Commodity, Currency, TradeStatus, TradeType, VolumeUnit


class CounterpartyCreate(BaseModel):
    name: str
    external_code: str | None = None


class CounterpartyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    external_code: str | None = None


class BookCreate(BaseModel):
    name: str
    description: str | None = None


class BookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None = None


class TradeCreate(BaseModel):
    trade_date: date
    counterparty_id: uuid.UUID
    book_id: uuid.UUID
    commodity: Commodity = Commodity.HENRY_HUB
    trade_type: TradeType
    buy_sell: BuySell
    volume: float
    volume_unit: VolumeUnit = VolumeUnit.MMBTU
    fixed_price: float
    price_currency: Currency = Currency.USD
    delivery_start_month: date
    delivery_end_month: date
    floating_index: str = "HENRY_HUB_PENULTIMATE"

    @model_validator(mode="after")
    def _check_ranges(self) -> "TradeCreate":
        if self.volume <= 0:
            raise ValueError("volume must be positive")
        if self.delivery_end_month < self.delivery_start_month:
            raise ValueError("delivery_end_month must not be before delivery_start_month")
        return self


class TradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    trade_date: date
    counterparty: CounterpartyRead
    book: BookRead
    commodity: Commodity
    trade_type: TradeType
    buy_sell: BuySell
    volume: float
    volume_unit: VolumeUnit
    fixed_price: float
    price_currency: Currency
    delivery_start_month: date
    delivery_end_month: date
    floating_index: str
    status: TradeStatus
    created_at: datetime
    updated_at: datetime
