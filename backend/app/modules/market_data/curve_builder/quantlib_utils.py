"""Thin QuantLib scaffolding: calendar/day-count conventions and date <-> ql.Date helpers.

Kept isolated from the rest of the app so `import QuantLib` stays confined to this module --
the bootstrapper works in plain `datetime.date` at its public boundary.
"""

from datetime import date

import QuantLib as ql


def trading_calendar() -> ql.Calendar:
    """v1 uses the US calendar as a stand-in for a NYMEX/Henry Hub trading calendar."""
    return ql.UnitedStates(ql.UnitedStates.NYSE)


def day_counter() -> ql.DayCounter:
    return ql.Actual365Fixed()


def to_ql_date(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def from_ql_date(d: ql.Date) -> date:
    return date(d.year(), d.month(), d.dayOfMonth())


def month_end(d: date) -> date:
    """Last calendar day of d's month, used to define delivery-period boundaries."""
    next_month = date(d.year + (d.month // 12), (d.month % 12) + 1, 1)
    return next_month.fromordinal(next_month.toordinal() - 1)
