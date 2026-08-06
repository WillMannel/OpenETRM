import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import Commodity
from app.modules.market_data.models import CurvePoint, ForwardCurve, MarketDataPoint


class MarketDataRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add_quote(self, quote: MarketDataPoint) -> MarketDataPoint:
        self._session.add(quote)
        await self._session.commit()
        await self._session.refresh(quote)
        return quote

    async def latest_quotes(self, commodity: Commodity, as_of_date: date) -> list[MarketDataPoint]:
        """One quote per delivery month: the most recent quote_date at or before as_of_date."""
        stmt = (
            select(MarketDataPoint)
            .where(MarketDataPoint.commodity == commodity, MarketDataPoint.quote_date <= as_of_date)
            .order_by(MarketDataPoint.delivery_month, MarketDataPoint.quote_date.desc())
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        # Keep only the newest quote_date per delivery_month (rows are already ordered for this).
        seen: set[date] = set()
        deduped: list[MarketDataPoint] = []
        for row in rows:
            if row.delivery_month not in seen:
                seen.add(row.delivery_month)
                deduped.append(row)
        return deduped

    async def save_curve(self, curve: ForwardCurve, points: list[CurvePoint]) -> ForwardCurve:
        self._session.add(curve)
        await (
            self._session.flush()
        )  # assigns curve.id (a Python-side default) before points reference it
        for point in points:
            point.curve_id = curve.id
            self._session.add(point)
        await self._session.commit()
        await self._session.refresh(curve)
        return curve

    async def get_curve(self, curve_id: uuid.UUID) -> ForwardCurve | None:
        # `points` relationship is lazy="selectin", so a plain get() eager-loads it.
        return await self._session.get(ForwardCurve, curve_id)

    async def price_history(
        self, commodity: Commodity, as_of_date: date, window_days: int
    ) -> list[MarketDataPoint]:
        """All quotes in the trailing `window_days` window, across all delivery months --
        the raw material for building the (quote_date x delivery_month) price panel used
        by historical-simulation VaR."""
        start = as_of_date - timedelta(days=window_days)
        stmt = (
            select(MarketDataPoint)
            .where(
                MarketDataPoint.commodity == commodity,
                MarketDataPoint.quote_date > start,
                MarketDataPoint.quote_date <= as_of_date,
            )
            .order_by(MarketDataPoint.quote_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_published_curve(
        self, commodity: Commodity, as_of_date: date
    ) -> ForwardCurve | None:
        stmt = (
            select(ForwardCurve)
            .where(ForwardCurve.commodity == commodity, ForwardCurve.as_of_date == as_of_date)
            .order_by(ForwardCurve.build_timestamp.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()
