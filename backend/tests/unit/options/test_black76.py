import math

import pytest

from app.common.enums import OptionType
from app.modules.valuation.options import black76_greeks, black76_price


def test_call_and_put_price_are_positive_for_at_the_money():
    call = black76_price(50.0, 50.0, 0.3, 0.5, 0.05, OptionType.CALL)
    put = black76_price(50.0, 50.0, 0.3, 0.5, 0.05, OptionType.PUT)
    assert call > 0
    assert put > 0


def test_put_call_parity_holds():
    """Black-76 put-call parity: C - P = e^{-rT}(F - K)."""
    forward, strike, vol, t, rate = 60.0, 55.0, 0.35, 1.0, 0.04
    call = black76_price(forward, strike, vol, t, rate, OptionType.CALL)
    put = black76_price(forward, strike, vol, t, rate, OptionType.PUT)
    expected_diff = math.exp(-rate * t) * (forward - strike)
    assert call - put == pytest.approx(expected_diff, rel=1e-6)


def test_deep_in_the_money_call_approaches_discounted_intrinsic():
    forward, strike, rate, t = 100.0, 10.0, 0.05, 1.0
    call = black76_price(forward, strike, 0.2, t, rate, OptionType.CALL)
    intrinsic = math.exp(-rate * t) * (forward - strike)
    assert call == pytest.approx(intrinsic, rel=1e-3)


def test_zero_time_to_expiry_returns_intrinsic_value():
    call = black76_price(55.0, 50.0, 0.3, 0.0, 0.05, OptionType.CALL)
    put = black76_price(45.0, 50.0, 0.3, 0.0, 0.05, OptionType.PUT)
    assert call == pytest.approx(5.0)
    assert put == pytest.approx(5.0)


def test_greeks_call_delta_between_zero_and_one():
    greeks = black76_greeks(50.0, 50.0, 0.3, 0.5, 0.05, OptionType.CALL)
    assert 0.0 < greeks.delta < 1.0
    assert greeks.gamma > 0
    assert greeks.vega > 0


def test_greeks_put_delta_between_negative_one_and_zero():
    greeks = black76_greeks(50.0, 50.0, 0.3, 0.5, 0.05, OptionType.PUT)
    assert -1.0 < greeks.delta < 0.0
    assert greeks.gamma > 0
    assert greeks.vega > 0


def test_greeks_gamma_and_vega_identical_for_call_and_put():
    call_greeks = black76_greeks(50.0, 48.0, 0.25, 0.75, 0.03, OptionType.CALL)
    put_greeks = black76_greeks(50.0, 48.0, 0.25, 0.75, 0.03, OptionType.PUT)
    assert call_greeks.gamma == pytest.approx(put_greeks.gamma)
    assert call_greeks.vega == pytest.approx(put_greeks.vega)


def test_degenerate_forward_returns_zero_greeks():
    greeks = black76_greeks(0.0, 50.0, 0.3, 0.5, 0.05, OptionType.CALL)
    assert greeks.delta == 0.0
    assert greeks.gamma == 0.0
    assert greeks.vega == 0.0
    assert greeks.theta == 0.0


def test_delta_matches_a_finite_difference_of_price():
    forward, strike, vol, t, rate = 50.0, 52.0, 0.28, 0.6, 0.04
    h = 0.01
    numerical_delta = (
        black76_price(forward + h, strike, vol, t, rate, OptionType.CALL)
        - black76_price(forward - h, strike, vol, t, rate, OptionType.CALL)
    ) / (2 * h)
    analytic_delta = black76_greeks(forward, strike, vol, t, rate, OptionType.CALL).delta
    assert analytic_delta == pytest.approx(numerical_delta, abs=1e-4)
