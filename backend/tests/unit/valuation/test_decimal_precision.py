"""Regression coverage for task P1-7 (Decimal money and unit-safe quantities end to
end): proves ValuationService.build_positions' net-volume/weighted-average-price
arithmetic is exact over many trades, and that this isn't academic -- these specific
inputs demonstrably drift under ordinary IEEE-754 float summation, which is exactly
what this module used to do (`float(t.volume)` at every trade, `sum(...)` over the
list) before this task.
"""

import uuid
from datetime import date
from decimal import Decimal

from app.common.enums import BuySell, Commodity, Currency, TradeStatus, TradeType, VolumeUnit
from app.modules.trade_capture.models import Trade
from app.modules.valuation.service import ValuationService

MONTH = date(2026, 6, 1)


def _trade(volume: str, fixed_price: str, book_id: uuid.UUID) -> Trade:
    return Trade(
        id=uuid.uuid4(),
        trade_date=date(2026, 1, 1),
        counterparty_id=uuid.uuid4(),
        book_id=book_id,
        commodity=Commodity.HENRY_HUB,
        trade_type=TradeType.SWAP,
        buy_sell=BuySell.BUY,
        volume=Decimal(volume),
        volume_unit=VolumeUnit.MMBTU,
        fixed_price=Decimal(fixed_price),
        price_currency=Currency.USD,
        delivery_start_month=MONTH,
        delivery_end_month=MONTH,
        status=TradeStatus.NEW,
    )


def test_naive_float_summation_of_these_inputs_actually_drifts():
    """Not testing production code -- this pins down *why* the fix in the next test
    matters. Ten trades of 0.1 MMBtu each is the textbook case: in binary float,
    0.1 has no exact representation, and summing it ten times does not land on
    exactly 1.0."""
    ten_tenths = [0.1] * 10
    assert sum(ten_tenths) != 1.0
    assert sum(ten_tenths) == 0.9999999999999999  # the actual (wrong) float result


def test_build_positions_nets_many_fractional_trades_exactly():
    book_id = uuid.uuid4()
    trades = [_trade("0.1", "3.00", book_id) for _ in range(10)]

    service = ValuationService.__new__(ValuationService)  # pure function, no DB needed
    positions = service.build_positions(trades, as_of_date=date(2026, 1, 15))

    assert len(positions) == 1
    # Exactly Decimal("1.0"), not something like Decimal("0.9999999999999999") -- see
    # test_naive_float_summation_of_these_inputs_actually_drifts for what the old
    # float-casting implementation would have produced from the same ten trades.
    assert positions[0].net_volume == Decimal("1.0")
    assert positions[0].avg_fixed_price == Decimal("3.00")


def test_build_positions_weighted_average_price_is_exact_over_many_trades():
    book_id = uuid.uuid4()
    # 30 trades of 0.1 @ varying prices that sum cleanly by hand: 10 @ 3.00, 10 @
    # 3.10, 10 @ 3.20 -- volume-weighted average is exactly 3.10.
    trades = (
        [_trade("0.1", "3.00", book_id) for _ in range(10)]
        + [_trade("0.1", "3.10", book_id) for _ in range(10)]
        + [_trade("0.1", "3.20", book_id) for _ in range(10)]
    )

    service = ValuationService.__new__(ValuationService)
    positions = service.build_positions(trades, as_of_date=date(2026, 1, 15))

    assert len(positions) == 1
    assert positions[0].net_volume == Decimal("3.0")
    assert positions[0].avg_fixed_price == Decimal("3.10")
