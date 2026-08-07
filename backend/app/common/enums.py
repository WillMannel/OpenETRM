"""Shared enums. v1 originally supported exactly one commodity, one currency, and one
volume unit -- Commodity now has a second value (WTI) to prove that's a real axis of
extension rather than a hardcoded assumption. See ARCHITECTURE.md for what's still
deliberately out of scope."""

import enum


class Commodity(str, enum.Enum):
    HENRY_HUB = "HENRY_HUB"
    WTI = "WTI"


class Currency(str, enum.Enum):
    USD = "USD"


class VolumeUnit(str, enum.Enum):
    MMBTU = "MMBTU"
    BBL = "BBL"


class TradeType(str, enum.Enum):
    SWAP = "SWAP"
    FORWARD = "FORWARD"
    OPTION = "OPTION"


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
