"""Black-76 pricing for commodity options: the standard model for options *on a
forward/future* (as opposed to Black-Scholes, which prices options on a spot asset --
the distinction matters because commodity options are conventionally struck against a
delivery-month forward, not a spot price). v1 has no implied-volatility surface, so a
flat volatility is captured on the trade itself at capture time
(Trade.option_volatility) -- a documented simplification, not a real vol surface; see
ARCHITECTURE.md and FUTURE_WORK.md.
"""

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from app.common.enums import OptionType


@dataclass
class OptionGreeks:
    delta: float
    gamma: float
    vega: float
    theta: float


def _d1_d2(forward: float, strike: float, volatility: float, t: float) -> tuple[float, float]:
    d1 = (np.log(forward / strike) + 0.5 * volatility**2 * t) / (volatility * np.sqrt(t))
    d2 = d1 - volatility * np.sqrt(t)
    return float(d1), float(d2)


def black76_price(
    forward: float,
    strike: float,
    volatility: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: OptionType,
) -> float:
    """Present value of one unit of a European option on a forward/future. Falls back
    to discounted intrinsic value (rather than raising) for a non-positive
    volatility/time-to-expiry/forward/strike, since this is called as one leg of a
    larger per-book valuation loop that shouldn't blow up on a degenerate input."""
    t = max(time_to_expiry_years, 0.0)
    discount = float(np.exp(-risk_free_rate * t))
    if t <= 0 or volatility <= 0 or forward <= 0 or strike <= 0:
        intrinsic = (
            max(forward - strike, 0.0)
            if option_type == OptionType.CALL
            else max(strike - forward, 0.0)
        )
        return intrinsic * discount

    d1, d2 = _d1_d2(forward, strike, volatility, t)
    if option_type == OptionType.CALL:
        return discount * (forward * float(norm.cdf(d1)) - strike * float(norm.cdf(d2)))
    return discount * (strike * float(norm.cdf(-d2)) - forward * float(norm.cdf(-d1)))


def black76_greeks(
    forward: float,
    strike: float,
    volatility: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: OptionType,
) -> OptionGreeks:
    """Delta (w.r.t. the forward), gamma, vega (per 1.0 = 100 vol points), and theta
    (per year) -- all per unit of volume. Degenerate inputs (non-positive vol/forward/
    strike) return all-zero greeks rather than raising."""
    t = max(time_to_expiry_years, 0.0)
    if t <= 0 or volatility <= 0 or forward <= 0 or strike <= 0:
        return OptionGreeks(delta=0.0, gamma=0.0, vega=0.0, theta=0.0)

    d1, _d2 = _d1_d2(forward, strike, volatility, t)
    discount = float(np.exp(-risk_free_rate * t))
    pdf_d1 = float(norm.pdf(d1))
    sqrt_t = float(np.sqrt(t))

    price = black76_price(forward, strike, volatility, t, risk_free_rate, option_type)
    if option_type == OptionType.CALL:
        delta = discount * float(norm.cdf(d1))
    else:
        delta = -discount * float(norm.cdf(-d1))

    gamma = discount * pdf_d1 / (forward * volatility * sqrt_t)
    vega = discount * forward * pdf_d1 * sqrt_t
    # Both call and put theta reduce to this same closed form once expressed in terms
    # of the already-computed price (see the derivation in Haug, "Option Pricing
    # Formulas", for the Black-76 model).
    theta = -(forward * discount * pdf_d1 * volatility) / (2 * sqrt_t) + risk_free_rate * price

    return OptionGreeks(delta=delta, gamma=gamma, vega=vega, theta=theta)
