from datetime import date
from decimal import Decimal

from app.modules.risk.var.pnl_attribution import TradeMonthSnapshot, attribute_pnl


def test_price_effect_only_for_a_trade_live_on_both_dates():
    """10,000 * (3.15 - 3.10) = 10,000 * 0.05 = 500.00."""
    month = date(2026, 6, 1)
    prior_date = date(2026, 1, 10)
    current_date = date(2026, 1, 11)
    snapshots = [
        TradeMonthSnapshot(
            delivery_month=month,
            signed_volume=Decimal(10_000),
            fixed_price=Decimal("3.00"),
            trade_date=date(2026, 1, 5),
        )
    ]

    result = attribute_pnl(
        snapshots,
        prior_date,
        current_date,
        prior_prices_by_month={month: Decimal("3.10")},
        current_prices_by_month={month: Decimal("3.15")},
    )

    assert result.price_effect == 500
    assert result.new_trade_effect == 0
    assert result.total == 500


def test_new_trade_effect_for_a_trade_booked_between_snapshots():
    """5,000 * (3.15 - 3.05) = 5,000 * 0.10 = 500.00."""
    month = date(2026, 6, 1)
    prior_date = date(2026, 1, 10)
    current_date = date(2026, 1, 11)
    snapshots = [
        TradeMonthSnapshot(
            delivery_month=month,
            signed_volume=Decimal(5_000),
            fixed_price=Decimal("3.05"),
            trade_date=date(2026, 1, 11),
        )
    ]

    result = attribute_pnl(
        snapshots,
        prior_date,
        current_date,
        prior_prices_by_month={month: Decimal("3.10")},
        current_prices_by_month={month: Decimal("3.15")},
    )

    assert result.price_effect == 0
    assert result.new_trade_effect == 500
    assert result.total == 500


def test_totals_sum_correctly_across_mixed_trades():
    """price_effect = 10,000 * 0.05 = 500; new_trade_effect = 5,000 * 0.10 = 500;
    total = 1,000 -- and, since this is Decimal arithmetic throughout (not float),
    exactly 1000, not something like 999.9999999999999."""
    month = date(2026, 6, 1)
    prior_date = date(2026, 1, 10)
    current_date = date(2026, 1, 11)
    snapshots = [
        TradeMonthSnapshot(
            month, Decimal(10_000), Decimal("3.00"), date(2026, 1, 5)
        ),  # live both days
        TradeMonthSnapshot(
            month, Decimal(5_000), Decimal("3.05"), date(2026, 1, 11)
        ),  # new since prior_date
    ]

    result = attribute_pnl(
        snapshots,
        prior_date,
        current_date,
        {month: Decimal("3.10")},
        {month: Decimal("3.15")},
    )

    assert result.price_effect == 500
    assert result.new_trade_effect == 500
    assert result.total == 1000


def test_skips_months_with_no_current_quote():
    month = date(2026, 6, 1)
    snapshots = [TradeMonthSnapshot(month, Decimal(10_000), Decimal("3.00"), date(2026, 1, 5))]

    result = attribute_pnl(
        snapshots,
        date(2026, 1, 10),
        date(2026, 1, 11),
        {month: Decimal("3.10")},
        current_prices_by_month={},
    )

    assert result.total == 0


def test_skips_prior_trades_with_no_prior_quote_rather_than_fabricating():
    month = date(2026, 6, 1)
    snapshots = [TradeMonthSnapshot(month, Decimal(10_000), Decimal("3.00"), date(2026, 1, 5))]

    result = attribute_pnl(
        snapshots,
        date(2026, 1, 10),
        date(2026, 1, 11),
        prior_prices_by_month={},
        current_prices_by_month={month: Decimal("3.15")},
    )

    assert result.total == 0
