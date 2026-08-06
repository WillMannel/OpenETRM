from app.modules.risk.var.sensitivities import bucketed_delta_ladder


def test_delta_ladder_matches_linear_position_volume():
    # revalue_fn is linear (volume * price per bucket), so delta should equal the volume exactly.
    volumes = {"2026-01": 100.0, "2026-02": -50.0}
    curve = {"2026-01": 3.0, "2026-02": 3.2}

    def revalue(prices: dict[str, float]) -> float:
        return sum(volumes[b] * p for b, p in prices.items())

    ladder = bucketed_delta_ladder(curve, revalue, bump_size=0.01)
    by_bucket = {d.tenor_bucket: d.delta_value for d in ladder}

    assert by_bucket["2026-01"] == 100.0
    assert by_bucket["2026-02"] == -50.0


def test_delta_ladder_zero_volume_bucket_has_zero_delta():
    curve = {"2026-01": 3.0}
    ladder = bucketed_delta_ladder(curve, revalue_fn=lambda prices: 0.0, bump_size=0.01)

    assert ladder[0].delta_value == 0.0
