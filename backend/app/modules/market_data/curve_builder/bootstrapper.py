"""Commodity forward-curve bootstrapping.

v1 quotes are already one-per-delivery-month, so the "bootstrap" is close to a direct
mapping -- but the function is deliberately structured the way `cmdty.curves` structures
its contract-period bootstrap (parse period -> allocate flat price segment -> assemble
curve) so it extends cleanly to finer-grained inputs later: daily quotes, balance-of-month
vs. calendar-month contracts, and quarter/season strips that need redistributing down to
months.
"""

from dataclasses import dataclass
from datetime import date

from app.common.exceptions import InsufficientMarketDataError


@dataclass(frozen=True)
class CurveSegment:
    """A single flat-price delivery-month segment of the bootstrapped curve."""

    delivery_month: date
    price: float

    @property
    def tenor_bucket(self) -> str:
        return f"{self.delivery_month.year:04d}-{self.delivery_month.month:02d}"


def bootstrap_monthly_curve(quotes: list[tuple[date, float]]) -> list[CurveSegment]:
    """Bootstrap a piecewise-flat monthly forward curve from (delivery_month, price) quotes.

    Each input quote is treated as the flat price for its entire delivery month (the
    standard convention for exchange-settled monthly commodity contracts, e.g. Henry Hub
    natural gas). Quotes are deduplicated by month (last one wins) and returned sorted by
    delivery month ascending.
    """
    if not quotes:
        raise InsufficientMarketDataError("no market data quotes supplied for curve build")

    by_month: dict[date, float] = {}
    for delivery_month, price in quotes:
        by_month[delivery_month.replace(day=1)] = price

    return [CurveSegment(delivery_month=month, price=by_month[month]) for month in sorted(by_month)]
