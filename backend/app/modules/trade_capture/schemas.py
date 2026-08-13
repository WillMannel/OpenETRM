import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.common.enums import (
    BuySell,
    ChangeRequestStatus,
    ChangeRequestType,
    Commodity,
    Currency,
    OptionType,
    PowerBlock,
    TradeStatus,
    TradeType,
    VolumeUnit,
)
from app.common.money import MoneyDecimal

_CERTIFICATE_TRADE_TYPES = (TradeType.REC, TradeType.EMISSIONS_ALLOWANCE)


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
    # None = unrestricted (no entitlement enforcement); set = only ADMIN or a
    # BookMembership holder may access this book. See app.modules.entitlements.
    desk_id: uuid.UUID | None = None


class TradeCreate(BaseModel):
    trade_date: date
    counterparty_id: uuid.UUID
    book_id: uuid.UUID
    commodity: Commodity = Commodity.HENRY_HUB
    trade_type: TradeType
    buy_sell: BuySell
    volume: MoneyDecimal
    volume_unit: VolumeUnit = VolumeUnit.MMBTU
    # Required for SWAP/FORWARD (the fixed leg's price); must be omitted for OPTION,
    # which is priced off strike_price/premium/option_volatility instead.
    fixed_price: MoneyDecimal | None = None
    price_currency: Currency = Currency.USD
    delivery_start_month: date
    delivery_end_month: date
    floating_index: str = "HENRY_HUB_PENULTIMATE"

    # OPTION-only. delivery_start_month doubles as the option's expiry convention (it
    # must be exercised/expire before physical/financial delivery begins).
    option_type: OptionType | None = None
    strike_price: MoneyDecimal | None = None
    premium: MoneyDecimal | None = None
    # float, deliberately: a quant model input, not exact trade economics -- see
    # Trade.option_volatility's docstring.
    option_volatility: float | None = None

    # POWER-only. See common.enums.PowerBlock.
    power_block: PowerBlock | None = None

    # REC / EMISSIONS_ALLOWANCE-only. delivery_start_month/delivery_end_month double
    # as the vintage (generation/issuance) period rather than a physical delivery
    # window for these two trade types.
    certificate_registry: str | None = None
    vintage_year: int | None = None

    @model_validator(mode="after")
    def _check_ranges(self) -> "TradeCreate":
        if self.volume <= 0:
            raise ValueError("volume must be positive")
        if self.delivery_end_month < self.delivery_start_month:
            raise ValueError("delivery_end_month must not be before delivery_start_month")

        option_fields = {
            "option_type": self.option_type,
            "strike_price": self.strike_price,
            "premium": self.premium,
            "option_volatility": self.option_volatility,
        }
        certificate_fields = {
            "certificate_registry": self.certificate_registry,
            "vintage_year": self.vintage_year,
        }

        if self.trade_type == TradeType.OPTION:
            missing = [name for name, value in option_fields.items() if value is None]
            if missing:
                raise ValueError(f"OPTION trades require: {sorted(missing)}")
            if self.strike_price <= 0:  # type: ignore[operator]
                raise ValueError("strike_price must be positive")
            if self.option_volatility <= 0:  # type: ignore[operator]
                raise ValueError("option_volatility must be positive")
            if self.fixed_price is not None:
                raise ValueError("fixed_price does not apply to OPTION trades")
            if any(v is not None for v in certificate_fields.values()):
                raise ValueError(
                    "certificate_registry/vintage_year only apply to REC/EMISSIONS_ALLOWANCE trades"
                )
        elif self.trade_type in _CERTIFICATE_TRADE_TYPES:
            missing = [name for name, value in certificate_fields.items() if value is None]
            if missing:
                raise ValueError(f"{self.trade_type.value} trades require: {sorted(missing)}")
            if any(v is not None for v in option_fields.values()):
                raise ValueError("option fields may only be set on an OPTION trade")
            if self.fixed_price is None:
                raise ValueError("fixed_price (price per certificate/allowance) is required")
        else:  # SWAP / FORWARD
            if any(v is not None for v in option_fields.values()):
                raise ValueError("option fields may only be set on an OPTION trade")
            if any(v is not None for v in certificate_fields.values()):
                raise ValueError(
                    "certificate_registry/vintage_year only apply to REC/EMISSIONS_ALLOWANCE trades"
                )
            if self.fixed_price is None:
                raise ValueError("fixed_price is required for SWAP/FORWARD trades")

        # power_block describes a delivery obligation, so it only applies to actual
        # power *delivery* products (SWAP/FORWARD/OPTION) -- not to a REC or emissions
        # allowance, even when those happen to be booked under commodity=POWER (a REC
        # represents the environmental attribute of 1 MWh, not a delivery block).
        is_power_delivery_product = (
            self.commodity == Commodity.POWER and self.trade_type not in _CERTIFICATE_TRADE_TYPES
        )
        if is_power_delivery_product:
            if self.power_block is None:
                raise ValueError("power_block is required for POWER SWAP/FORWARD/OPTION trades")
        elif self.power_block is not None:
            raise ValueError("power_block only applies to POWER SWAP/FORWARD/OPTION trades")

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
    volume: MoneyDecimal
    volume_unit: VolumeUnit
    fixed_price: MoneyDecimal | None
    price_currency: Currency
    delivery_start_month: date
    delivery_end_month: date
    floating_index: str
    option_type: OptionType | None
    strike_price: MoneyDecimal | None
    premium: MoneyDecimal | None
    option_volatility: float | None
    power_block: PowerBlock | None
    certificate_registry: str | None
    vintage_year: int | None
    status: TradeStatus
    version: int
    previous_version_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


# Fields an amendment may change. Deliberately a subset of TradeCreate -- counterparty,
# book, and commodity are not amendable (those would really be "cancel and rebook").
_AMENDABLE_FIELDS = {
    "trade_type",
    "buy_sell",
    "volume",
    "volume_unit",
    "fixed_price",
    "price_currency",
    "delivery_start_month",
    "delivery_end_month",
    "floating_index",
    "option_type",
    "strike_price",
    "premium",
    "option_volatility",
    "power_block",
    "certificate_registry",
    "vintage_year",
}


class AmendmentRequestCreate(BaseModel):
    changes: dict[str, Any] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _check_fields(self) -> "AmendmentRequestCreate":
        unknown = set(self.changes) - _AMENDABLE_FIELDS
        if unknown:
            raise ValueError(
                f"not amendable: {sorted(unknown)} (allowed: {sorted(_AMENDABLE_FIELDS)})"
            )
        return self


class CancellationRequestCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ReviewDecision(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class TradeChangeRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    trade_id: uuid.UUID
    change_type: ChangeRequestType
    status: ChangeRequestStatus
    proposed_changes: dict[str, Any] | None
    reason: str
    requested_by_user_id: uuid.UUID
    requested_at: datetime
    reviewed_by_user_id: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None
