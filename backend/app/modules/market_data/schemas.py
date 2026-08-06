import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.common.enums import Commodity, CurveMethod, CurveStatus, MarketDataSource


class MarketDataPointCreate(BaseModel):
    commodity: Commodity = Commodity.HENRY_HUB
    quote_date: date
    delivery_month: date
    price: float
    source: MarketDataSource = MarketDataSource.SEED


class MarketDataPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    commodity: Commodity
    quote_date: date
    delivery_month: date
    price: float
    source: MarketDataSource


class CurveBuildRequest(BaseModel):
    commodity: Commodity = Commodity.HENRY_HUB
    as_of_date: date


class CurvePointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    delivery_month: date
    price: float
    tenor_bucket: str


class ForwardCurveRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    commodity: Commodity
    as_of_date: date
    build_timestamp: datetime
    method: CurveMethod
    status: CurveStatus
    points: list[CurvePointRead] = []
