"""Shared enums. Commodity started as one value (HENRY_HUB) to prove the platform
wasn't hardcoded to it; it now covers the products a power-and-gas trading desk
actually trades day to day (power, gas, oil, coal) plus two environmental certificate
products (REC, EMISSIONS_ALLOWANCE) that are captured/lifecycle-managed but not yet
curve-valued -- see LINEAR_TRADE_TYPES and FUTURE_WORK.md for what's still
deliberately out of scope (FTRs, multi-hub/basis trading, BTM PPA economics)."""

import enum


class Commodity(str, enum.Enum):
    HENRY_HUB = "HENRY_HUB"
    WTI = "WTI"
    COAL = "COAL"
    POWER = "POWER"


class Currency(str, enum.Enum):
    USD = "USD"


class VolumeUnit(str, enum.Enum):
    MMBTU = "MMBTU"
    BBL = "BBL"
    MWH = "MWH"
    METRIC_TON = "METRIC_TON"


class PowerBlock(str, enum.Enum):
    """The defining characteristic of an OTC power product -- which hours of the day
    the delivery obligation covers. v1 values against the same monthly curve price
    regardless of block (documented simplification: no separate peak/off-peak curves
    yet -- see FUTURE_WORK.md). Only meaningful for Commodity.POWER trades."""

    ON_PEAK = "ON_PEAK"  # conventionally 5x16: weekday HE7-HE22
    OFF_PEAK = "OFF_PEAK"  # conventionally 7x8 + weekend/holiday hours
    FLAT = "FLAT"  # 7x24 / around-the-clock


class TradeType(str, enum.Enum):
    SWAP = "SWAP"
    FORWARD = "FORWARD"
    OPTION = "OPTION"
    REC = "REC"
    EMISSIONS_ALLOWANCE = "EMISSIONS_ALLOWANCE"


LINEAR_TRADE_TYPES = frozenset({TradeType.SWAP, TradeType.FORWARD})
"""Trade types with a payoff linear in volume, netted into Position by
ValuationService.build_positions and curve-valued in mark_to_market. OPTION is valued
individually instead (Black-76, non-linear payoff -- see valuation/options.py).
REC/EMISSIONS_ALLOWANCE are fully captured and lifecycle-managed (create/confirm/
amend/cancel/audit/limits) but not yet curve-valued in v1: unlike a delivery-month
forward curve, there's no natural reference-price time series for a certificate/
allowance in this platform yet, and fabricating one would be worse than not marking it
at all. See FUTURE_WORK.md."""


class OptionType(str, enum.Enum):
    CALL = "CALL"
    PUT = "PUT"


class BuySell(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, enum.Enum):
    """A trade's lifecycle state. NEW is a draft that doesn't count toward positions
    until CONFIRMED. PENDING_AMENDMENT/PENDING_CANCELLATION trades still count (they're
    economically live until the change is approved or rejected). AMENDED means this row
    has been superseded by a newer version (see Trade.previous_version_id on the new
    row) and no longer counts. CANCELLED trades never count."""

    NEW = "NEW"
    CONFIRMED = "CONFIRMED"
    PENDING_AMENDMENT = "PENDING_AMENDMENT"
    PENDING_CANCELLATION = "PENDING_CANCELLATION"
    AMENDED = "AMENDED"
    CANCELLED = "CANCELLED"


LIVE_TRADE_STATUSES = frozenset(
    {TradeStatus.CONFIRMED, TradeStatus.PENDING_AMENDMENT, TradeStatus.PENDING_CANCELLATION}
)
"""Statuses that count toward positions/valuation/risk -- draft (NEW), superseded
(AMENDED), and CANCELLED trades are excluded."""


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
    PARAMETRIC = "PARAMETRIC"
    MONTE_CARLO = "MONTE_CARLO"


class ConfidenceLevel(int, enum.Enum):
    PCT_95 = 95
    PCT_99 = 99


class UserRole(str, enum.Enum):
    """VIEWER: read-only. TRADER: capture trades, request amendments/cancellations.
    RISK_MANAGER: everything TRADER can view, run risk, approve/reject change requests
    and confirmations. ADMIN: RISK_MANAGER plus user management. Four-eyes is enforced
    at the service layer (an approver may not be the same user who requested the
    change), not by role alone."""

    VIEWER = "VIEWER"
    TRADER = "TRADER"
    RISK_MANAGER = "RISK_MANAGER"
    ADMIN = "ADMIN"


class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    CONFIRM = "CONFIRM"
    REQUEST_AMENDMENT = "REQUEST_AMENDMENT"
    REQUEST_CANCELLATION = "REQUEST_CANCELLATION"
    APPROVE_CHANGE = "APPROVE_CHANGE"
    REJECT_CHANGE = "REJECT_CHANGE"
    LIMIT_BREACH = "LIMIT_BREACH"
    ACKNOWLEDGE_LIMIT_BREACH = "ACKNOWLEDGE_LIMIT_BREACH"


class ChangeRequestType(str, enum.Enum):
    AMENDMENT = "AMENDMENT"
    CANCELLATION = "CANCELLATION"


class ChangeRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LimitType(str, enum.Enum):
    """VOLUME: max absolute net volume (per delivery month) a book may hold in a given
    commodity. VAR: max 1-day VaR (at the limit's configured confidence level) a book
    may run before it's flagged."""

    VOLUME = "VOLUME"
    VAR = "VAR"


class LimitBreachStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
