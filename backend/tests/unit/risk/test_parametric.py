from datetime import date, timedelta

import pandas as pd
import pytest

from app.modules.risk.var.historical_sim import VarInput
from app.modules.risk.var.parametric import parametric_var


def _price_panel(daily_changes: list[float], month: date) -> pd.DataFrame:
    prices = [10.0]
    for change in daily_changes:
        prices.append(prices[-1] + change)
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(len(prices))]
    return pd.DataFrame({month: prices}, index=pd.Index(dates, name="quote_date"))


def test_parametric_var_is_zero_for_flat_prices():
    month = date(2026, 6, 1)
    panel = _price_panel([0.0] * 10, month)
    net_volume = pd.Series({month: 1000.0})

    var_value = parametric_var(VarInput(panel, net_volume), confidence_level=95)

    assert var_value == 0.0


def test_parametric_var_scales_with_position_size():
    month = date(2026, 6, 1)
    panel = _price_panel([1, -2, 3, -2, 1, -1, 2, -3, 1, -1], month)

    small = parametric_var(VarInput(panel, pd.Series({month: 100.0})), confidence_level=95)
    large = parametric_var(VarInput(panel, pd.Series({month: 1000.0})), confidence_level=95)

    assert large == pytest.approx(small * 10, rel=1e-6)


def test_parametric_var_increases_with_confidence_level():
    month = date(2026, 6, 1)
    panel = _price_panel([1, -2, 3, -2, 1, -1, 2, -3, 1, -1], month)
    net_volume = pd.Series({month: 1000.0})

    var_95 = parametric_var(VarInput(panel, net_volume), confidence_level=95)
    var_99 = parametric_var(VarInput(panel, net_volume), confidence_level=99)

    assert var_99 > var_95


def test_parametric_var_is_nonnegative_for_short_position():
    month = date(2026, 6, 1)
    panel = _price_panel([2, -1, 3, -2, 1], month)
    net_volume = pd.Series({month: -500.0})

    assert parametric_var(VarInput(panel, net_volume), confidence_level=99) >= 0.0
