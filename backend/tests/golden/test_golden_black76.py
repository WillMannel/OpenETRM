"""Golden Black-76 option prices/greeks: expected values come from a reference
formula written fresh in this file (see reference_black76_price/reference_black76_greeks
below), not from running app.modules.valuation.options once and pinning whatever it
returned. See tests/golden/README.md for why that distinction matters.

The reference implementation deliberately restructures the computation (single
function handling both call/put via a `is_call` bool, d1/d2 recomputed independently)
so a bug in the production code's control flow -- e.g. a swapped d1/d2, a missing
discount factor, `norm.cdf(d2)` where it should be `norm.cdf(-d2)` for a put -- shows
up as a mismatch here even though it wouldn't show up in a put-call-parity or
finite-difference check against the *same* implementation (see
tests/unit/options/test_black76.py for those complementary checks).
"""

import numpy as np
import pytest
from scipy.stats import norm

from app.common.enums import OptionType
from app.modules.valuation.options import black76_greeks, black76_price


def reference_black76_price(
    forward: float, strike: float, sigma: float, t: float, r: float, is_call: bool
) -> float:
    d1 = (np.log(forward / strike) + 0.5 * sigma**2 * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    discount = np.exp(-r * t)
    if is_call:
        return float(discount * (forward * norm.cdf(d1) - strike * norm.cdf(d2)))
    return float(discount * (strike * norm.cdf(-d2) - forward * norm.cdf(-d1)))


def reference_black76_greeks(
    forward: float, strike: float, sigma: float, t: float, r: float, is_call: bool
) -> tuple[float, float, float, float]:
    d1 = (np.log(forward / strike) + 0.5 * sigma**2 * t) / (sigma * np.sqrt(t))
    discount = np.exp(-r * t)
    pdf_d1 = norm.pdf(d1)
    sqrt_t = np.sqrt(t)
    price = reference_black76_price(forward, strike, sigma, t, r, is_call)
    delta = discount * norm.cdf(d1) if is_call else -discount * norm.cdf(-d1)
    gamma = discount * pdf_d1 / (forward * sigma * sqrt_t)
    vega = discount * forward * pdf_d1 * sqrt_t
    theta = -(forward * discount * pdf_d1 * sigma) / (2 * sqrt_t) + r * price
    return float(delta), float(gamma), float(vega), float(theta)


# (forward, strike, sigma, t, r, option_type, label) -- a spread of ATM/ITM/OTM,
# short/long maturity, low/high vol so a formula bug in any one term is likely to move
# at least one of these off its pinned value.
PRICE_CASES = [
    (50.0, 50.0, 0.20, 1.0, 0.05, OptionType.CALL, "ATM call"),
    (50.0, 50.0, 0.20, 1.0, 0.05, OptionType.PUT, "ATM put"),
    (60.0, 55.0, 0.35, 1.0, 0.04, OptionType.CALL, "ITM call"),
    (60.0, 55.0, 0.35, 1.0, 0.04, OptionType.PUT, "OTM put (same market)"),
    (45.0, 50.0, 0.25, 0.5, 0.03, OptionType.CALL, "OTM call, short maturity"),
    (45.0, 50.0, 0.25, 0.5, 0.03, OptionType.PUT, "ITM put, short maturity"),
]


@pytest.mark.parametrize("forward,strike,sigma,t,r,option_type,label", PRICE_CASES)
def test_black76_price_matches_independent_reference(
    forward, strike, sigma, t, r, option_type, label
):
    expected = reference_black76_price(forward, strike, sigma, t, r, option_type == OptionType.CALL)
    actual = black76_price(forward, strike, sigma, t, r, option_type)
    assert actual == pytest.approx(expected, rel=1e-9), label


# Pinned to 10 decimal places computed once via reference_black76_price (see
# tests/golden/README.md) -- a human-readable anchor independent of parametrize/scipy
# version drift, in case scipy's norm.cdf implementation itself ever changes precision.
GOLDEN_ATM_CALL_PRICE = 3.7885410732
GOLDEN_ITM_CALL_PRICE = 10.3100506478
GOLDEN_OTM_PUT_PRICE = 5.5061034521


def test_black76_atm_call_matches_pinned_literal():
    price = black76_price(50.0, 50.0, 0.20, 1.0, 0.05, OptionType.CALL)
    assert price == pytest.approx(GOLDEN_ATM_CALL_PRICE, abs=1e-8)


def test_black76_itm_call_matches_pinned_literal():
    price = black76_price(60.0, 55.0, 0.35, 1.0, 0.04, OptionType.CALL)
    assert price == pytest.approx(GOLDEN_ITM_CALL_PRICE, abs=1e-8)


def test_black76_otm_put_matches_pinned_literal():
    price = black76_price(60.0, 55.0, 0.35, 1.0, 0.04, OptionType.PUT)
    assert price == pytest.approx(GOLDEN_OTM_PUT_PRICE, abs=1e-8)


@pytest.mark.parametrize(
    "forward,strike,sigma,t,r,option_type,label",
    [
        (50.0, 50.0, 0.20, 1.0, 0.05, OptionType.CALL, "ATM call greeks"),
        (50.0, 50.0, 0.20, 1.0, 0.05, OptionType.PUT, "ATM put greeks"),
    ],
)
def test_black76_greeks_match_independent_reference(
    forward, strike, sigma, t, r, option_type, label
):
    expected_delta, expected_gamma, expected_vega, expected_theta = reference_black76_greeks(
        forward, strike, sigma, t, r, option_type == OptionType.CALL
    )
    greeks = black76_greeks(forward, strike, sigma, t, r, option_type)
    assert greeks.delta == pytest.approx(expected_delta, rel=1e-9), label
    assert greeks.gamma == pytest.approx(expected_gamma, rel=1e-9), label
    assert greeks.vega == pytest.approx(expected_vega, rel=1e-9), label
    assert greeks.theta == pytest.approx(expected_theta, rel=1e-9), label


def test_black76_atm_call_delta_matches_pinned_literal():
    # Pinned once via reference_black76_greeks -- see tests/golden/README.md.
    greeks = black76_greeks(50.0, 50.0, 0.20, 1.0, 0.05, OptionType.CALL)
    assert greeks.delta == pytest.approx(0.51350012, abs=1e-6)
    assert greeks.gamma == pytest.approx(0.03775929, abs=1e-6)
    assert greeks.vega == pytest.approx(18.87964716, abs=1e-4)
    assert greeks.theta == pytest.approx(-1.69853766, abs=1e-6)
