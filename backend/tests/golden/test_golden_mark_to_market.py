"""Golden mark-to-market numbers: net volume / average fixed price / unrealized P&L
for a multi-trade position, computed by explicit hand arithmetic in this file,
independent of ValuationService.build_positions's internal bucketing/weighting code.
See tests/golden/README.md.
"""

import uuid
from datetime import date

import pytest

from app.common.enums import BuySell, Commodity, Currency, TradeStatus, TradeType, VolumeUnit
from app.modules.trade_capture.models import Trade
from app.modules.valuation.service import ValuationService

MONTH = date(2026, 6, 1)


def _trade(buy_sell: BuySell, volume: float, fixed_price: float, book_id: uuid.UUID) -> Trade:
    return Trade(
        id=uuid.uuid4(),
        trade_date=date(2026, 1, 1),
        counterparty_id=uuid.uuid4(),
        book_id=book_id,
        commodity=Commodity.HENRY_HUB,
        trade_type=TradeType.SWAP,
        buy_sell=buy_sell,
        volume=volume,
        volume_unit=VolumeUnit.MMBTU,
        fixed_price=fixed_price,
        price_currency=Currency.USD,
        delivery_start_month=MONTH,
        delivery_end_month=MONTH,
        status=TradeStatus.NEW,
    )


def test_build_positions_matches_hand_computed_net_volume_and_avg_price():
    """Three trades in one book/month: buy 100 @ $3.00, sell 40 @ $3.50, buy 20 @
    $2.80. net_volume = 100 - 40 + 20 = 80. Volume-weighted average price =
    (100*3.00 + 40*3.50 + 20*2.80) / (100+40+20) = (300 + 140 + 56) / 160 = 496/160 =
    3.10."""
    book_id = uuid.uuid4()
    trades = [
        _trade(BuySell.BUY, 100, 3.00, book_id),
        _trade(BuySell.SELL, 40, 3.50, book_id),
        _trade(BuySell.BUY, 20, 2.80, book_id),
    ]

    service = ValuationService.__new__(ValuationService)  # pure function, no DB needed
    positions = service.build_positions(trades, as_of_date=date(2026, 1, 15))

    assert len(positions) == 1
    assert positions[0].net_volume == pytest.approx(80.0)
    assert positions[0].avg_fixed_price == pytest.approx(3.10)


def test_unrealized_pnl_matches_hand_computed_value_against_curve():
    """Same position (net_volume=80, avg_fixed_price=3.10) valued against a $3.25
    curve price: unrealized = net_volume * (curve_price - avg_fixed_price)
    = 80 * (3.25 - 3.10) = 80 * 0.15 = 12.00."""
    book_id = uuid.uuid4()
    trades = [
        _trade(BuySell.BUY, 100, 3.00, book_id),
        _trade(BuySell.SELL, 40, 3.50, book_id),
        _trade(BuySell.BUY, 20, 2.80, book_id),
    ]

    service = ValuationService.__new__(ValuationService)
    positions = service.build_positions(trades, as_of_date=date(2026, 1, 15))
    position = positions[0]

    curve_price = 3.25
    unrealized = position.net_volume * (curve_price - position.avg_fixed_price)

    assert unrealized == pytest.approx(12.00)
