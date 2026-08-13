"""Stress testing: apply named, predefined shocks to the curve and report the P&L
impact of each. Unlike VaR (a statistical statement about *likely* loss), a stress
scenario is a deliberate "what if" -- useful precisely because it isn't bounded by
recent historical volatility the way historical-sim/parametric/Monte Carlo VaR are.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

ShockType = Literal["absolute", "percentage"]


@dataclass(frozen=True)
class StressScenario:
    name: str
    shock_type: ShockType
    shock_value: (
        float  # absolute: $/unit shift applied to every bucket; percentage: e.g. -0.10 = -10%
    )


@dataclass(frozen=True)
class StressResult:
    scenario_name: str
    pnl_impact: float


DEFAULT_SCENARIOS: list[StressScenario] = [
    StressScenario("Parallel +10%", "percentage", 0.10),
    StressScenario("Parallel -10%", "percentage", -0.10),
    StressScenario("Absolute +$0.50", "absolute", 0.50),
    StressScenario("Absolute -$0.50", "absolute", -0.50),
]


def run_stress_scenarios(
    curve_prices_by_bucket: dict[str, float],
    revalue_fn: Callable[[dict[str, float]], float],
    scenarios: list[StressScenario] | None = None,
) -> list[StressResult]:
    scenarios = scenarios if scenarios is not None else DEFAULT_SCENARIOS
    base_mtm = revalue_fn(curve_prices_by_bucket)

    results = []
    for scenario in scenarios:
        shocked_curve = {
            bucket: (
                price + scenario.shock_value
                if scenario.shock_type == "absolute"
                else price * (1 + scenario.shock_value)
            )
            for bucket, price in curve_prices_by_bucket.items()
        }
        shocked_mtm = revalue_fn(shocked_curve)
        results.append(StressResult(scenario_name=scenario.name, pnl_impact=shocked_mtm - base_mtm))
    return results
