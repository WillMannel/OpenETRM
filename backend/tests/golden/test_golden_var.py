"""Golden VaR numbers: expected values are derived by hand-traceable arithmetic on a
tiny, fully-enumerated scenario set -- small enough that every step (the simulated P&L
list, the sort, the percentile interpolation, the sample variance) is spelled out in a
comment, not just re-run blind through NumPy/SciPy a second time. See
tests/golden/README.md for why a golden test needs an independently-derived expected
value rather than a captured-current-output snapshot.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.modules.risk.var.historical_sim import VarInput, historical_var
from app.modules.risk.var.parametric import parametric_var

MONTH = date(2026, 6, 1)


def _price_panel(prices: list[float]) -> pd.DataFrame:
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(len(prices))]
    return pd.DataFrame({MONTH: prices}, index=pd.Index(dates, name="quote_date"))


# Prices 10, 11, 9, 12, 8 -> day-over-day changes +1, -2, +3, -4.
PRICES = [10.0, 11.0, 9.0, 12.0, 8.0]
CHANGES = [1.0, -2.0, 3.0, -4.0]


def test_historical_var_matches_hand_computed_percentile_long_95():
    """Long 1,000 units: simulated P&L per historical day = volume * change =
    [1000, -2000, 3000, -4000]. Sorted ascending: [-4000, -2000, 1000, 3000].
    NumPy's default ('linear') percentile interpolation for the 5th percentile of 4
    sorted values: index = (n-1)*q = 3*0.05 = 0.15 -> interpolate between sorted[0]=
    -4000 and sorted[1]=-2000: -4000 + 0.15*(-2000 - -4000) = -4000 + 300 = -3700.
    VaR = -(-3700) = 3700."""
    panel = _price_panel(PRICES)
    net_volume = pd.Series({MONTH: 1000.0})

    var_value = historical_var(VarInput(panel, net_volume), confidence_level=95)

    assert var_value == pytest.approx(3700.0)


def test_historical_var_matches_hand_computed_percentile_long_99():
    """Same scenario set, 99% confidence -> 1st percentile: index = 3*0.01 = 0.03 ->
    -4000 + 0.03*(-2000 - -4000) = -4000 + 60 = -3940. VaR = 3940."""
    panel = _price_panel(PRICES)
    net_volume = pd.Series({MONTH: 1000.0})

    var_value = historical_var(VarInput(panel, net_volume), confidence_level=99)

    assert var_value == pytest.approx(3940.0)


def test_historical_var_matches_hand_computed_percentile_short_95():
    """Short 500 units: simulated P&L = -500 * changes = [-500, 1000, -1500, 2000].
    Sorted ascending: [-1500, -500, 1000, 2000]. 5th percentile: index = 3*0.05 = 0.15
    -> -1500 + 0.15*(-500 - -1500) = -1500 + 150 = -1350. VaR = 1350."""
    panel = _price_panel(PRICES)
    net_volume = pd.Series({MONTH: -500.0})

    var_value = historical_var(VarInput(panel, net_volume), confidence_level=95)

    assert var_value == pytest.approx(1350.0)


def test_parametric_var_matches_hand_computed_variance_95():
    """Sample variance (ddof=1, matching pandas .cov()) of [1, -2, 3, -4]: mean=-0.5;
    squared deviations from mean = [2.25, 2.25, 12.25, 12.25], sum=29.0, /(n-1)=/3 =
    9.6667 -> std = 3.10913. Portfolio std = |weight| * std = 1000 * 3.10913 =
    3109.13. VaR = z_0.95 * portfolio_std = 1.644854 * 3109.13 = 5114.06."""
    panel = _price_panel(PRICES)
    net_volume = pd.Series({MONTH: 1000.0})

    var_value = parametric_var(VarInput(panel, net_volume), confidence_level=95)

    assert var_value == pytest.approx(5114.057755, rel=1e-6)


def test_parametric_var_matches_hand_computed_variance_99():
    """Same portfolio std (3109.13), z_0.99 = 2.326348 -> VaR = 7232.91."""
    panel = _price_panel(PRICES)
    net_volume = pd.Series({MONTH: 1000.0})

    var_value = parametric_var(VarInput(panel, net_volume), confidence_level=99)

    assert var_value == pytest.approx(7232.909477, rel=1e-6)


def test_parametric_var_reproduces_independent_numpy_variance_computation():
    """Belt-and-braces: recompute the sample variance and z-score independently (via
    numpy/scipy, not by re-deriving the arithmetic by hand as in the tests above) to
    catch a mismatch the hand-computed cases might share a blind spot with."""
    from scipy.stats import norm

    changes = np.array(CHANGES)
    sample_var = changes.var(ddof=1)
    portfolio_std = 1000.0 * np.sqrt(sample_var)
    expected = norm.ppf(0.95) * portfolio_std

    panel = _price_panel(PRICES)
    net_volume = pd.Series({MONTH: 1000.0})
    var_value = parametric_var(VarInput(panel, net_volume), confidence_level=95)

    assert var_value == pytest.approx(float(expected), rel=1e-9)
