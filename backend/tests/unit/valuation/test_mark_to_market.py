import uuid
from datetime import date

from app.common.enums import BuySell, Commodity, Currency, TradeStatus, TradeType, VolumeUnit
from app.modules.trade_capture.models import Trade
from app.modules.valuation.service import ValuationService


def _trade(
    buy_sell: BuySell, volume: float, fixed_price: float, month: date, book_id: uuid.UUID
) -> Trade:
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
        delivery_start_month=month,
        delivery_end_month=month,
        status=TradeStatus.NEW,
    )


def test_build_positions_nets_buy_and_sell_in_same_month():
    book_id = uuid.uuid4()
    month = date(2026, 6, 1)
    trades = [
        _trade(BuySell.BUY, 100, 3.0, month, book_id),
        _trade(BuySell.SELL, 40, 3.5, month, book_id),
    ]

    service = ValuationService.__new__(ValuationService)  # no DB needed for this pure function
    positions = service.build_positions(trades, as_of_date=date(2026, 1, 15))

    assert len(positions) == 1
    assert positions[0].net_volume == 60  # 100 buy - 40 sell
    assert positions[0].delivery_month == month


def test_build_positions_spans_multiple_delivery_months():
    book_id = uuid.uuid4()
    trades = [_trade(BuySell.BUY, 50, 3.0, date(2026, 1, 1), book_id)]

    service = ValuationService.__new__(ValuationService)
    trades[0].delivery_start_month = date(2026, 1, 1)
    trades[0].delivery_end_month = date(2026, 3, 1)
    positions = service.build_positions(trades, as_of_date=date(2026, 1, 1))

    assert [p.delivery_month for p in positions] == [
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
    ]
    assert all(p.net_volume == 50 for p in positions)
