"""Shared enums. v1 intentionally supports exactly one commodity, one currency, and one
volume unit -- see ARCHITECTURE.md for what's deliberately out of scope."""

import enum


class Commodity(str, enum.Enum):
    HENRY_HUB = "HENRY_HUB"


class Currency(str, enum.Enum):
    USD = "USD"


class VolumeUnit(str, enum.Enum):
    MMBTU = "MMBTU"


class TradeType(str, enum.Enum):
    SWAP = "SWAP"
    FORWARD = "FORWARD"


class BuySell(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, enum.Enum):
    NEW = "NEW"
    VALIDATED = "VALIDATED"
    CANCELLED = "CANCELLED"


class MarketDataSource(str, enum.Enum):
    SEED = "SEED"
    MANUAL = "MANUAL"


class CurveMethod(str, enum.Enum):
    PIECEWISE_FLAT_MONTHLY = "PIECEWISE_FLAT_MONTHLY"


class CurveStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class VarMethod(str, enum.Enum):
    HISTORICAL_SIM = "HISTORICAL_SIM"


class ConfidenceLevel(int, enum.Enum):
    PCT_95 = 95
    PCT_99 = 99
