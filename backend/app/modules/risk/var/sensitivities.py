"""Bump-and-revalue sensitivities: a PV01-style bucketed delta ladder.

For each tenor bucket (delivery month) in the curve, bump that month's price by
`bump_size`, revalue the position with `revalue_fn`, and take the finite-difference
delta relative to the base valuation. This is intentionally the simplest correct
approach (one bump per bucket, no cross terms) -- swap in analytic/AD-based greeks later
if bump-and-revalue performance becomes a bottleneck.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class DeltaBucket:
    tenor_bucket: str
    delta_value: float
    bump_size: float


def bucketed_delta_ladder(
    curve_prices_by_bucket: dict[str, float],
    revalue_fn: Callable[[dict[str, float]], float],
    bump_size: float = 0.01,
) -> list[DeltaBucket]:
    """`revalue_fn` takes a {tenor_bucket: price} curve and returns the position's MTM value."""
    base_mtm = revalue_fn(curve_prices_by_bucket)

    ladder: list[DeltaBucket] = []
    for bucket, price in curve_prices_by_bucket.items():
        bumped_curve = dict(curve_prices_by_bucket)
        bumped_curve[bucket] = price + bump_size
        bumped_mtm = revalue_fn(bumped_curve)
        delta = (bumped_mtm - base_mtm) / bump_size
        ladder.append(DeltaBucket(tenor_bucket=bucket, delta_value=delta, bump_size=bump_size))
    return ladder
