import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import Commodity, ConfidenceLevel, VarMethod


class VarRunRequest(BaseModel):
    book_id: uuid.UUID | None = None
    as_of_date: date
    commodity: Commodity = Commodity.HENRY_HUB
    confidence_level: ConfidenceLevel = ConfidenceLevel.PCT_95
    scenario_window_days: int = 250
    method: VarMethod = VarMethod.HISTORICAL_SIM


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


class DeltaLadderRunRequest(BaseModel):
    book_id: uuid.UUID
    as_of_date: date
    commodity: Commodity = Commodity.HENRY_HUB


class StressScenarioIn(BaseModel):
    name: str
    shock_type: Literal["absolute", "percentage"]
    shock_value: float


class StressTestRequest(BaseModel):
    book_id: uuid.UUID
    as_of_date: date
    commodity: Commodity = Commodity.HENRY_HUB
    # None -> the module's DEFAULT_SCENARIOS (a standard +/-10% and +/-$0.50 set).
    scenarios: list[StressScenarioIn] | None = None


class StressResultRead(BaseModel):
    scenario_name: str
    pnl_impact: float


class StressTestResponse(BaseModel):
    book_id: uuid.UUID
    as_of_date: date
    results: list[StressResultRead]


class PnlAttributionRequest(BaseModel):
    book_id: uuid.UUID
    prior_date: date
    current_date: date
    commodity: Commodity = Commodity.HENRY_HUB


class PnlAttributionResponse(BaseModel):
    book_id: uuid.UUID
    prior_date: date
    current_date: date
    price_effect: float
    new_trade_effect: float = Field(
        description="MTM of trades booked between prior_date and current_date"
    )
    total: float


class OptionGreeksRequest(BaseModel):
    book_id: uuid.UUID
    as_of_date: date
    commodity: Commodity = Commodity.HENRY_HUB


class OptionGreeksRead(BaseModel):
    trade_id: uuid.UUID
    delta: float
    gamma: float
    vega: float
    theta: float


class OptionGreeksResponse(BaseModel):
    book_id: uuid.UUID
    as_of_date: date
    results: list[OptionGreeksRead]
