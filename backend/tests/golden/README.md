# Golden-numbers test harness

## Why this directory exists

An audit of the existing test suite found ~129 status-code/shape assertions against
only ~22 assertions that pinned an actual numeric result. That ratio lets a quant
module's arithmetic drift silently -- a wrong sign, a swapped `d1`/`d2`, a percentile
computed against the wrong tail, a discount factor applied twice -- while every test
still goes green, because most tests only check "did this return 200" or "is this
positive", never "is this the number it should be."

This directory is where every quant-output test lives whose expected value was
**derived independently of the production code under test**, not captured by running
the implementation once and asserting whatever it produced. The distinction matters:
asserting "the code returns 3.7885" because that's what it happened to return the day
the test was written protects against nothing -- a bug that was there when the test was
written stays invisible forever. A golden test asserts "the code returns 3.7885 because
a Black-76 call with these inputs, computed by an independently-written reference
formula, *is* 3.7885" -- so a bug in the production formula (wrong sign, wrong
argument order, a percentile off by one) shows up as a real failure.

## Methodology used in this directory

- **Option pricing** (`test_golden_black76.py`): each expected price/greek is computed
  by a reference Black-76 implementation written fresh inside the test file --
  structurally independent of `app.modules.valuation.options` (different function
  shape, d1/d2 recomputed from scratch) even though both correctly rely on
  `scipy.stats.norm.cdf`/`.pdf` as a trusted primitive. This catches formula-assembly
  bugs (a swapped argument, a missing discount factor, a sign error in the put
  formula); it would not catch both implementations sharing the same fundamental
  misunderstanding of Black-76 itself, which is out of scope for a unit-level pin.
- **VaR** (`test_golden_var.py`): expected values are computed by hand-traceable
  arithmetic on a tiny, fully-enumerated scenario set (a handful of daily price changes
  on one contract) -- small enough that the percentile/variance computation is checked
  in a code comment showing the sorted scenario list and the exact interpolation or
  variance arithmetic used, not just re-run through NumPy/SciPy blind.
- **Mark-to-market** (`test_golden_mark_to_market.py`): expected net volume / average
  price / unrealized P&L for a multi-trade position are computed by explicit
  hand arithmetic in the test, independent of `ValuationService.build_positions`'s
  internal bucketing logic.
- **Monte Carlo VaR** (`test_golden_monte_carlo.py`): Monte Carlo is inherently
  stochastic, so there's no closed-form expected value to derive independently. Instead
  a *fixed-seed* run's output is pinned only after `test_monte_carlo.py` has already
  cross-checked that seed's result against parametric VaR (same inputs, analytic
  method) to within a documented tolerance -- the pin then protects that already-verified
  number from silently drifting, e.g. from a numpy/scipy version bump changing RNG
  behavior or a refactor changing the simulation logic.

## The CI gate

`scripts/check_quant_golden_coverage.py` runs in CI (`quant-golden-coverage` job) and
fails the build if:
1. any module on the hardcoded quant-module list has no associated golden test file, or
2. that file's count of numeric pin assertions (`pytest.approx(...)` / bare `== <literal
   number>`) drops below its recorded floor.

Raise the floor in the script whenever you add more golden coverage; never lower it to
make a change pass.
