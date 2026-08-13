#!/usr/bin/env python3
"""CI gate: every quant module must have a golden-numbers test file (see
tests/golden/README.md) with at least its recorded floor of numeric-pin assertions.

This exists because a prior audit found the test suite had ~129 status-code/shape
assertions against only ~22 numeric-result assertions -- a ratio that lets a quant
module's arithmetic drift silently while every test stays green. This script doesn't
try to police that ratio suite-wide (most of the suite is legitimately testing
HTTP/RBAC/workflow behavior, where a status-code assertion *is* the right assertion);
it polices the specific set of modules that produce a number a trader or risk manager
would act on, requiring each one to carry independently-derived numeric pins.

A "numeric-pin assertion" here is any assert of the form `pytest.approx(...)` or a bare
`== <numeric literal>` -- both indicate the test is pinning a specific expected value,
as opposed to `assert x > 0` / `assert response.status_code == 200`, which pin a
property or a status, not a value.

Usage: python scripts/check_quant_golden_coverage.py
Exit code 0 if every module meets its floor, 1 otherwise (with a report of shortfalls).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# A numeric-pin assertion: pytest.approx(...) anywhere on the line, or a bare
# `== <number>` comparison (handles negative numbers, decimals, and Python's
# underscore-grouped literals like 10_000).
_NUMERIC_PIN_RE = re.compile(r"pytest\.approx\(|==\s*-?\d[\d_]*(\.\d+)?\b")


@dataclass(frozen=True)
class QuantModule:
    module_path: str  # relative to backend/app, for the report only
    golden_files: tuple[str, ...]  # relative to backend/tests, must all exist
    min_numeric_pins: int  # floor across all golden_files combined; raise, never lower


# Raise `min_numeric_pins` whenever more golden coverage is added for a module. Never
# lower it to make a change pass -- that defeats the point of the gate.
QUANT_MODULES: tuple[QuantModule, ...] = (
    QuantModule(
        "modules/valuation/options.py",
        ("golden/test_golden_black76.py",),
        min_numeric_pins=10,
    ),
    QuantModule(
        "modules/valuation/service.py",
        ("golden/test_golden_mark_to_market.py", "unit/valuation/test_mark_to_market.py"),
        min_numeric_pins=4,
    ),
    QuantModule(
        "modules/risk/var/historical_sim.py",
        ("golden/test_golden_var.py",),
        min_numeric_pins=3,
    ),
    QuantModule(
        "modules/risk/var/parametric.py",
        ("golden/test_golden_var.py",),
        min_numeric_pins=3,
    ),
    QuantModule(
        "modules/risk/var/monte_carlo.py",
        ("golden/test_golden_monte_carlo.py",),
        min_numeric_pins=2,
    ),
    QuantModule(
        "modules/risk/var/sensitivities.py",
        ("unit/risk/test_sensitivities.py",),
        min_numeric_pins=2,
    ),
    QuantModule(
        "modules/risk/var/stress.py",
        ("unit/risk/test_stress.py",),
        min_numeric_pins=2,
    ),
    QuantModule(
        "modules/risk/var/pnl_attribution.py",
        ("unit/risk/test_pnl_attribution.py",),
        min_numeric_pins=5,
    ),
    QuantModule(
        "modules/market_data/curve_builder/bootstrapper.py",
        ("unit/market_data/test_bootstrapper.py",),
        min_numeric_pins=1,
    ),
)


def count_numeric_pins(path: Path) -> int:
    text = path.read_text()
    return len(_NUMERIC_PIN_RE.findall(text))


def main() -> int:
    tests_dir = REPO_ROOT / "tests"
    failures: list[str] = []

    for module in QUANT_MODULES:
        total_pins = 0
        missing_files: list[str] = []
        for rel in module.golden_files:
            path = tests_dir / rel
            if not path.exists():
                missing_files.append(rel)
                continue
            total_pins += count_numeric_pins(path)

        if missing_files:
            failures.append(f"  {module.module_path}: missing golden test file(s) {missing_files}")
        elif total_pins < module.min_numeric_pins:
            failures.append(
                f"  {module.module_path}: only {total_pins} numeric-pin assertions "
                f"across {module.golden_files}, need >= {module.min_numeric_pins}"
            )
        else:
            print(f"OK  {module.module_path}: {total_pins} numeric-pin assertions")

    if failures:
        print("\nquant-golden-coverage FAILED:", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        print(
            "\nAdd/expand a golden test in tests/golden/ (see tests/golden/README.md) "
            "before merging a change to one of these modules.",
            file=sys.stderr,
        )
        return 1

    print(f"\nquant-golden-coverage OK: all {len(QUANT_MODULES)} quant modules covered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
