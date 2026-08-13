"""Task P1-13 (closing P1-9's identified-not-fixed scale gap -- see PERFORMANCE.md
and ARCHITECTURE.md's "Scale and performance"): TradeRepository.list_live must not
eager-load Trade.counterparty/.book, unlike TradeRepository.list/.get which need
them for TradeRead. Proven here via SQLAlchemy's own unloaded-attribute inspection
rather than a wall-clock timing assertion (timing is inherently flaky in a shared
CI runner; "was the join actually skipped" is a deterministic yes/no)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import BuySell, Commodity, Currency, TradeStatus, TradeType, VolumeUnit
from app.modules.trade_capture.models import Book, Counterparty, Trade
from app.modules.trade_capture.repository import TradeRepository


async def _seed_live_trade(db_session: AsyncSession) -> None:
    counterparty = Counterparty(name="Lean Query Counterparty")
    book = Book(name="Lean Query Book")
    db_session.add_all([counterparty, book])
    await db_session.flush()
    db_session.add(
        Trade(
            trade_date=date(2026, 1, 10),
            counterparty_id=counterparty.id,
            book_id=book.id,
            commodity=Commodity.HENRY_HUB,
            trade_type=TradeType.SWAP,
            buy_sell=BuySell.BUY,
            volume=Decimal(1000),
            volume_unit=VolumeUnit.MMBTU,
            fixed_price=Decimal("3.00"),
            price_currency=Currency.USD,
            delivery_start_month=date(2026, 6, 1),
            delivery_end_month=date(2026, 6, 1),
            status=TradeStatus.CONFIRMED,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_live_does_not_eager_load_counterparty_or_book(db_session: AsyncSession):
    await _seed_live_trade(db_session)

    trades = await TradeRepository(db_session).list_live()
    assert len(trades) == 1

    unloaded = inspect(trades[0]).unloaded
    assert "counterparty" in unloaded
    assert "book" in unloaded


@pytest.mark.asyncio
async def test_list_still_eager_loads_counterparty_and_book_for_the_blotter(
    db_session: AsyncSession,
):
    """The trade-blotter/detail-view methods are unaffected by list_live's
    lazyload override -- TradeRead needs counterparty/book names, and this proves
    the leaner query is scoped to list_live specifically, not a model-wide
    regression."""
    await _seed_live_trade(db_session)

    trades = await TradeRepository(db_session).list()
    assert len(trades) == 1

    unloaded = inspect(trades[0]).unloaded
    assert "counterparty" not in unloaded
    assert "book" not in unloaded
