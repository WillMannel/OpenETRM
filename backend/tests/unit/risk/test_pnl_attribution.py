from datetime import date

from app.modules.risk.var.pnl_attribution import TradeMonthSnapshot, attribute_pnl


def test_price_effect_only_for_a_trade_live_on_both_dates():
    month = date(2026, 6, 1)
    prior_date = date(2026, 1, 10)
    current_date = date(2026, 1, 11)
    snapshots = [
        TradeMonthSnapshot(
            delivery_month=month,
            signed_volume=10_000,
            fixed_price=3.00,
            trade_date=date(2026, 1, 5),
        )
    ]

    result = attribute_pnl(
        snapshots,
        prior_date,
        current_date,
        prior_prices_by_month={month: 3.10},
        current_prices_by_month={month: 3.15},
    )

    assert result.price_effect == 10_000 * (3.15 - 3.10)
    assert result.new_trade_effect == 0.0
    assert result.total == result.price_effect


def test_new_trade_effect_for_a_trade_booked_between_snapshots():
    month = date(2026, 6, 1)
    prior_date = date(2026, 1, 10)
    current_date = date(2026, 1, 11)
    snapshots = [
        TradeMonthSnapshot(
            delivery_month=month,
            signed_volume=5_000,
            fixed_price=3.05,
            trade_date=date(2026, 1, 11),
        )
    ]

    result = attribute_pnl(
        snapshots,
        prior_date,
        current_date,
        prior_prices_by_month={month: 3.10},
        current_prices_by_month={month: 3.15},
    )

    assert result.price_effect == 0.0
    assert result.new_trade_effect == 5_000 * (3.15 - 3.05)
    assert result.total == result.new_trade_effect


def test_totals_sum_correctly_across_mixed_trades():
    month = date(2026, 6, 1)
    prior_date = date(2026, 1, 10)
    current_date = date(2026, 1, 11)
    snapshots = [
        TradeMonthSnapshot(month, 10_000, 3.00, date(2026, 1, 5)),  # live both days
        TradeMonthSnapshot(month, 5_000, 3.05, date(2026, 1, 11)),  # new since prior_date
    ]

    result = attribute_pnl(snapshots, prior_date, current_date, {month: 3.10}, {month: 3.15})

    expected_price = 10_000 * (3.15 - 3.10)
    expected_new = 5_000 * (3.15 - 3.05)
    assert result.price_effect == expected_price
    assert result.new_trade_effect == expected_new
    assert result.total == expected_price + expected_new


def test_skips_months_with_no_current_quote():
    month = date(2026, 6, 1)
    snapshots = [TradeMonthSnapshot(month, 10_000, 3.00, date(2026, 1, 5))]

    result = attribute_pnl(
        snapshots, date(2026, 1, 10), date(2026, 1, 11), {month: 3.10}, current_prices_by_month={}
    )

    assert result.total == 0.0


def test_skips_prior_trades_with_no_prior_quote_rather_than_fabricating():
    month = date(2026, 6, 1)
    snapshots = [TradeMonthSnapshot(month, 10_000, 3.00, date(2026, 1, 5))]

    result = attribute_pnl(
        snapshots,
        date(2026, 1, 10),
        date(2026, 1, 11),
        prior_prices_by_month={},
        current_prices_by_month={month: 3.15},
    )

    assert result.total == 0.0
