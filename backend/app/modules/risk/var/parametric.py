"""Parametric (variance-covariance) VaR.

Fits a covariance matrix to historical day-over-day price changes per delivery-month
contract, then computes portfolio variance analytically as w^T . Sigma . w (w = net
volume per contract), and VaR as z_alpha * portfolio_std_dev -- the standard
delta-normal approach. Faster than historical/Monte Carlo simulation and the textbook
baseline method, at the cost of assuming price changes are (multivariate) normal.
"""

import numpy as np
from scipy.stats import norm

from app.modules.risk.var.historical_sim import VarInput


def parametric_var(inp: VarInput, confidence_level: int, horizon_days: int = 1) -> float:
    history = inp.price_history.sort_index()
    if len(history) < 2:
        return 0.0

    changes = history.diff().dropna(how="all").fillna(0.0)
    months = inp.net_volume_by_month.index.intersection(changes.columns)
    if months.empty:
        return 0.0

    weights = inp.net_volume_by_month.reindex(months).fillna(0.0).to_numpy()
    cov_matrix = changes[months].cov().to_numpy()

    portfolio_variance = float(weights @ cov_matrix @ weights)
    portfolio_std_dev = np.sqrt(max(portfolio_variance, 0.0))

    z_score = norm.ppf(confidence_level / 100)
    var_value = z_score * portfolio_std_dev * np.sqrt(horizon_days)
    return max(float(var_value), 0.0)
