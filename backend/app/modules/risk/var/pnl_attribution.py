"""P&L attribution: decompose the change in a book's MTM between two dates into
"price movement" (trades that were live on both dates, revalued at each day's curve)
and "new trade" (trades booked between the two dates) effects.

Deliberately trade-level, not position-level: attributing off the position-level
avg_fixed_price (an abs-volume-weighted average across possibly-mixed buy/sell trades
in the same month -- see ValuationService.build_positions) doesn't cleanly reconcile
when volume changes between snapshots. Summing signed_volume * (price - fixed_price)
trade-by-trade does reconcile by construction: it's just addition regrouped.

What this does NOT capture: trades that were live on the prior date but are no longer
live on the current date (cancelled/amended away in between) -- that needs a historical
status snapshot per date, which the data model doesn't have yet (Trade only carries its
*current* status). Documented as a known gap rather than silently wrong; see
ARCHITECTURE.md.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class TradeMonthSnapshot:
    """One (trade, delivery-month) pair -- a trade spanning several months contributes
    one of these per month, all with the same signed_volume/fixed_price/trade_date."""

    delivery_month: date
    signed_volume: Decimal
    fixed_price: Decimal
    trade_date: date


@dataclass(frozen=True)
class PnlAttribution:
    price_effect: Decimal
    new_trade_effect: Decimal
    total: Decimal


def attribute_pnl(
    snapshots: list[TradeMonthSnapshot],
    prior_date: date,
    current_date: date,
    prior_prices_by_month: dict[date, Decimal],
    current_prices_by_month: dict[date, Decimal],
) -> PnlAttribution:
    # Decimal accumulators, not float -- this sums signed_volume * price_delta
    # trade-by-trade over a book's entire live trade population, the same
    # unbounded-summation-over-many-trades shape as ValuationService.build_positions
    # (see app.common.money's module docstring for why that matters).
    price_effect = Decimal(0)
    new_trade_effect = Decimal(0)

    for snap in snapshots:
        current_price = current_prices_by_month.get(snap.delivery_month)
        if current_price is None:
            continue  # no current quote for this month; skip rather than fabricate

        if snap.trade_date <= prior_date:
            prior_price = prior_prices_by_month.get(snap.delivery_month)
            if prior_price is None:
                continue  # no prior quote either; can't attribute this one
            price_effect += snap.signed_volume * (current_price - prior_price)
        elif snap.trade_date <= current_date:
            new_trade_effect += snap.signed_volume * (current_price - snap.fixed_price)
        # trade_date > current_date shouldn't occur (caller only passes live trades as
        # of current_date) but is silently skipped rather than raising, just in case.

    return PnlAttribution(
        price_effect=price_effect,
        new_trade_effect=new_trade_effect,
        total=price_effect + new_trade_effect,
    )
