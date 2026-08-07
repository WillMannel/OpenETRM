from datetime import date, timedelta

import pandas as pd
import pytest

from app.modules.risk.var.historical_sim import VarInput
from app.modules.risk.var.monte_carlo import monte_carlo_var
from app.modules.risk.var.parametric import parametric_var


def _price_panel(daily_changes: list[float], month: date) -> pd.DataFrame:
    prices = [10.0]
    for change in daily_changes:
        prices.append(prices[-1] + change)
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(len(prices))]
    return pd.DataFrame({month: prices}, index=pd.Index(dates, name="quote_date"))


def test_monte_carlo_var_is_near_zero_for_flat_prices():
    # Not exactly zero: monte_carlo_var adds a tiny diagonal jitter to the covariance
    # matrix for numerical stability (see its docstring), so a handful of scenarios
    # draw a whisker of noise even when the historical sample itself is dead flat.
    month = date(2026, 6, 1)
    panel = _price_panel([0.0] * 10, month)
    net_volume = pd.Series({month: 1000.0})

    var_value = monte_carlo_var(VarInput(panel, net_volume), confidence_level=95, seed=42)

    assert var_value < 0.1


def test_monte_carlo_var_roughly_agrees_with_parametric_for_linear_payoff():
    # v1's payoffs are linear (swaps/forwards), so Monte Carlo (which doesn't assume the
    # *portfolio* P&L is normal, only that price changes are) should converge close to
    # parametric VaR (which assumes both) given enough draws -- that's the whole point
    # of the multivariate-normal Monte Carlo model here, and a useful sanity check.
    month = date(2026, 6, 1)
    changes = [1, -2, 3, -2, 1, -1, 2, -3, 1, -1, 2, -1, 1, -2, 2]
    panel = _price_panel(changes, month)
    net_volume = pd.Series({month: 1000.0})

    mc_var = monte_carlo_var(
        VarInput(panel, net_volume), confidence_level=95, num_simulations=50_000, seed=7
    )
    param_var = parametric_var(VarInput(panel, net_volume), confidence_level=95)

    assert mc_var == pytest.approx(param_var, rel=0.15)


def test_monte_carlo_var_is_reproducible_with_a_seed():
    month = date(2026, 6, 1)
    panel = _price_panel([1, -2, 3, -2, 1, -1, 2, -3, 1, -1], month)
    net_volume = pd.Series({month: 1000.0})

    first = monte_carlo_var(VarInput(panel, net_volume), confidence_level=95, seed=123)
    second = monte_carlo_var(VarInput(panel, net_volume), confidence_level=95, seed=123)

    assert first == second


def test_monte_carlo_var_is_nonnegative_for_short_position():
    month = date(2026, 6, 1)
    panel = _price_panel([2, -1, 3, -2, 1], month)
    net_volume = pd.Series({month: -500.0})

    assert monte_carlo_var(VarInput(panel, net_volume), confidence_level=99, seed=1) >= 0.0
