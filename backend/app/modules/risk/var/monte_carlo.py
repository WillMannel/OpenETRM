"""Monte Carlo VaR.

Fits a multivariate normal to historical day-over-day price changes (same inputs as
parametric.py), then draws many simulated scenarios from it, revalues the position
under each, and takes the empirical percentile -- unlike parametric VaR this doesn't
assume the portfolio's P&L distribution itself is normal (only that the underlying
price-change draws are), so it degrades more gracefully for a book with option-like,
non-linear payoffs later. For v1's linear swap/forward payoffs the two methods should
agree closely; that's a useful sanity check, not a coincidence.
"""

import numpy as np

from app.modules.risk.var.historical_sim import VarInput


def monte_carlo_var(
    inp: VarInput,
    confidence_level: int,
    horizon_days: int = 1,
    num_simulations: int = 10_000,
    seed: int | None = None,
) -> float:
    history = inp.price_history.sort_index()
    if len(history) < 2:
        return 0.0

    changes = history.diff().dropna(how="all").fillna(0.0)
    months = inp.net_volume_by_month.index.intersection(changes.columns)
    if months.empty:
        return 0.0

    mean = changes[months].mean().to_numpy()
    cov_matrix = changes[months].cov().to_numpy()
    # Tiny diagonal jitter: with few historical observations relative to the number of
    # contracts, the sample covariance can be near-singular, which multivariate_normal
    # rejects outright. This is standard regularization, not a hidden assumption change.
    cov_matrix = cov_matrix + np.eye(len(months)) * 1e-10

    rng = np.random.default_rng(seed)
    simulated_changes = rng.multivariate_normal(mean, cov_matrix, size=num_simulations)

    weights = inp.net_volume_by_month.reindex(months).fillna(0.0).to_numpy()
    simulated_pnl = simulated_changes @ weights
    if horizon_days != 1:
        simulated_pnl = simulated_pnl * np.sqrt(horizon_days)

    loss_tail_percentile = 100 - confidence_level
    var_at_confidence = np.percentile(simulated_pnl, loss_tail_percentile)
    return max(float(-var_at_confidence), 0.0)
