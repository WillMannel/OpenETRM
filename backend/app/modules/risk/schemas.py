import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.common.enums import Commodity, ConfidenceLevel


class VarRunRequest(BaseModel):
    book_id: uuid.UUID | None = None
    as_of_date: date
    commodity: Commodity = Commodity.HENRY_HUB
    confidence_level: ConfidenceLevel = ConfidenceLevel.PCT_95
    scenario_window_days: int = 250


class VarResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID | None
    as_of_date: date
    confidence_level: int
    horizon_days: int
    method: str
    scenario_window_days: int
    var_value: float
    computed_at: datetime


class SensitivityResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tenor_bucket: str
    delta_value: float
    bump_size: float


class DeltaLadderRead(BaseModel):
    book_id: uuid.UUID
    as_of_date: date
    curve_id: uuid.UUID
    buckets: list[SensitivityResultRead]
