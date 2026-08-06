from datetime import date

import pytest

from app.common.exceptions import InsufficientMarketDataError
from app.modules.market_data.curve_builder.bootstrapper import bootstrap_monthly_curve


def test_bootstrap_sorts_and_dedupes_by_month():
    quotes = [
        (date(2026, 3, 15), 3.10),
        (date(2026, 1, 5), 2.80),
        (date(2026, 2, 10), 2.95),
        (date(2026, 1, 20), 2.85),  # later quote for Jan -> should win over 2.80
    ]

    segments = bootstrap_monthly_curve(quotes)

    assert [s.delivery_month for s in segments] == [
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
    ]
    assert segments[0].price == 2.85
    assert segments[0].tenor_bucket == "2026-01"


def test_bootstrap_rejects_empty_quotes():
    with pytest.raises(InsufficientMarketDataError):
        bootstrap_monthly_curve([])
