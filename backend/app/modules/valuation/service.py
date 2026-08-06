"""Mark-to-market valuation: aggregate trades into positions, value each position's
remaining delivery months against a published forward curve.

Sign convention: BUY is a long position (positive volume), SELL is short (negative
volume). MTM value of a position = net_volume * (curve_price - avg_fixed_price) for a
swap/forward, i.e. the standard fixed-for-floating settlement payoff.
"""

import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import BuySell, Commodity
from app.common.exceptions import NotFoundError
from app.modules.market_data.repository import MarketDataRepository
from app.modules.trade_capture.models import Trade
from app.modules.valuation.models import Position, ValuationResult


def _month_range(start: date, end: date) -> list[date]:
    months = []
    cursor = start.replace(day=1)
    end_marker = end.replace(day=1)
    while cursor <= end_marker:
        months.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


class ValuationService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._market_data_repo = MarketDataRepository(session)

    async def _trades_for_book(self, book_id: uuid.UUID) -> list[Trade]:
        result = await self._session.execute(select(Trade).where(Trade.book_id == book_id))
        return list(result.scalars().all())

    def build_positions(self, trades: list[Trade], as_of_date: date) -> list[Position]:
        """Roll trades up into net volume / average fixed price per delivery month."""
        buckets: dict[date, list[Trade]] = defaultdict(list)
        for trade in trades:
            for month in _month_range(trade.delivery_start_month, trade.delivery_end_month):
                buckets[month].append(trade)

        positions: list[Position] = []
        for month, month_trades in sorted(buckets.items()):
            signed_volumes = [
                (float(t.volume) if t.buy_sell == BuySell.BUY else -float(t.volume))
                for t in month_trades
            ]
            net_volume = sum(signed_volumes)
            total_abs_volume = sum(abs(v) for v in signed_volumes) or 1.0
            avg_price = (
                sum(
                    abs(v) * float(t.fixed_price)
                    for v, t in zip(signed_volumes, month_trades, strict=True)
                )
                / total_abs_volume
            )

            positions.append(
                Position(
                    book_id=month_trades[0].book_id,
                    commodity=month_trades[0].commodity,
                    delivery_month=month,
                    net_volume=net_volume,
                    avg_fixed_price=avg_price,
                    as_of_date=as_of_date,
                )
            )
        return positions

    async def mark_to_market(
        self, book_id: uuid.UUID, as_of_date: date, commodity: Commodity
    ) -> tuple[list[Position], list[ValuationResult]]:
        curve = await self._market_data_repo.get_published_curve(commodity, as_of_date)
        if curve is None:
            raise NotFoundError("ForwardCurve", f"{commodity}@{as_of_date}")

        trades = await self._trades_for_book(book_id)
        positions = self.build_positions(trades, as_of_date)
        curve_price_by_month = {p.delivery_month: float(p.price) for p in curve.points}

        results: list[ValuationResult] = []
        for position in positions:
            curve_price = curve_price_by_month.get(position.delivery_month)
            if curve_price is None:
                # No market quote for this delivery month yet; skip rather than fabricate a value.
                continue
            unrealized = position.net_volume * (curve_price - position.avg_fixed_price)
            results.append(
                ValuationResult(
                    trade_id=None,
                    book_id=book_id,
                    as_of_date=as_of_date,
                    curve_id=curve.id,
                    mtm_value=unrealized,
                    realized_pnl=0,
                    unrealized_pnl=unrealized,
                )
            )
            self._session.add(position)
        for result in results:
            self._session.add(result)
        await self._session.commit()
        return positions, results
