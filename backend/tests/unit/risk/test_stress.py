import pytest

from app.modules.risk.var.stress import DEFAULT_SCENARIOS, StressScenario, run_stress_scenarios


def _revalue(volumes: dict[str, float]):
    def _fn(prices: dict[str, float]) -> float:
        return sum(volumes[b] * p for b, p in prices.items())

    return _fn


def test_percentage_shock_scales_with_price():
    curve = {"2026-01": 4.0}
    revalue = _revalue({"2026-01": 100.0})
    scenario = StressScenario("up 10%", "percentage", 0.10)

    results = run_stress_scenarios(curve, revalue, [scenario])

    # base mtm = 100*4.0 = 400; shocked = 100*4.4 = 440; impact = +40
    assert results[0].pnl_impact == pytest.approx(40.0)


def test_absolute_shock_is_price_independent_of_magnitude():
    curve = {"2026-01": 4.0}
    revalue = _revalue({"2026-01": 100.0})
    scenario = StressScenario("down $0.50", "absolute", -0.50)

    results = run_stress_scenarios(curve, revalue, [scenario])

    assert results[0].pnl_impact == -50.0


def test_short_position_has_opposite_sign_impact():
    curve = {"2026-01": 4.0}
    long_revalue = _revalue({"2026-01": 100.0})
    short_revalue = _revalue({"2026-01": -100.0})
    scenario = StressScenario("up 10%", "percentage", 0.10)

    long_impact = run_stress_scenarios(curve, long_revalue, [scenario])[0].pnl_impact
    short_impact = run_stress_scenarios(curve, short_revalue, [scenario])[0].pnl_impact

    assert long_impact == -short_impact


def test_default_scenarios_run_without_error_and_cover_both_directions():
    curve = {"2026-01": 4.0, "2026-02": 4.2}
    revalue = _revalue({"2026-01": 100.0, "2026-02": -50.0})

    results = run_stress_scenarios(curve, revalue)

    assert len(results) == len(DEFAULT_SCENARIOS)
    impacts = [r.pnl_impact for r in results]
    assert any(i > 0 for i in impacts)
    assert any(i < 0 for i in impacts)
