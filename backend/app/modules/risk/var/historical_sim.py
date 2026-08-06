"""Historical-simulation VaR.

Takes a price panel (rows = historical quote_date, columns = delivery-month contract,
values = settlement price) plus the current position's net volume per delivery month.
Each historical day's day-over-day price *change* is treated as one scenario: reapply it
to today's curve, revalue the position, and collect the resulting simulated P&L. VaR is
then the relevant lower-tail percentile of that simulated P&L distribution.

This is the standard, simplest form of historical VaR (unweighted, full revaluation via
linear price-change scenarios) -- deliberately not filtered/weighted historical
simulation, which is future work once there's a real need for it.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class VarInput:
    price_history: pd.DataFrame  # index: quote_date, columns: delivery_month, values: price
    net_volume_by_month: pd.Series  # index: delivery_month, values: net position volume


def historical_var(inp: VarInput, confidence_level: int, horizon_days: int = 1) -> float:
    """Returns VaR as a positive number (a loss magnitude) at the given confidence level."""
    history = inp.price_history.sort_index()
    if len(history) < 2:
        return 0.0

    price_changes = (
        history.diff().dropna(how="all").fillna(0.0)
    )  # day-over-day $ change per contract

    months = inp.net_volume_by_month.index.intersection(price_changes.columns)
    if months.empty:
        return 0.0

    volumes = inp.net_volume_by_month.reindex(months).fillna(0.0).to_numpy()
    scenario_changes = price_changes[months].to_numpy()  # shape: (n_scenarios, n_months)

    simulated_pnl = scenario_changes @ volumes  # one simulated P&L per historical day
    if horizon_days != 1:
        simulated_pnl = simulated_pnl * np.sqrt(horizon_days)  # square-root-of-time scaling

    loss_tail_percentile = 100 - confidence_level
    var_at_confidence = np.percentile(simulated_pnl, loss_tail_percentile)
    return float(max(-var_at_confidence, 0.0))
