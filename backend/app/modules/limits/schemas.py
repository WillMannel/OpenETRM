import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import Commodity, LimitBreachStatus, LimitType
from app.common.money import MoneyDecimal


class BookLimitCreate(BaseModel):
    book_id: uuid.UUID
    commodity: Commodity = Commodity.HENRY_HUB
    limit_type: LimitType
    threshold: MoneyDecimal = Field(gt=0)
    confidence_level: int = 95


class BookLimitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID
    commodity: Commodity
    limit_type: LimitType
    threshold: MoneyDecimal
    confidence_level: int
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class LimitBreachRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    limit_id: uuid.UUID
    book_id: uuid.UUID
    commodity: Commodity
    limit_type: LimitType
    threshold: MoneyDecimal
    observed_value: MoneyDecimal
    as_of_date: date
    status: LimitBreachStatus
    occurred_at: datetime
    acknowledged_by_user_id: uuid.UUID | None
    acknowledged_at: datetime | None


class AcknowledgeBreachRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
