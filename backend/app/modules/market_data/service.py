import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import Commodity, CurveStatus
from app.common.exceptions import NotFoundError
from app.common.money import to_decimal
from app.modules.market_data.curve_builder.bootstrapper import bootstrap_monthly_curve
from app.modules.market_data.models import CurvePoint, ForwardCurve, MarketDataPoint
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.schemas import MarketDataPointCreate


class MarketDataService:
    def __init__(self, session: AsyncSession):
        self._repo = MarketDataRepository(session)

    async def add_quote(self, payload: MarketDataPointCreate) -> MarketDataPoint:
        return await self._repo.add_quote(MarketDataPoint(**payload.model_dump()))

    async def build_curve(self, commodity: Commodity, as_of_date: date) -> ForwardCurve:
        """Bootstrap and persist a forward curve from the latest quotes as of `as_of_date`.

        Synchronous by design here; `app.tasks.curve_tasks` wraps this same call as a
        background job once curve builds need to run off the request/response cycle.
        """
        quotes = await self._repo.latest_quotes(commodity, as_of_date)
        segments = bootstrap_monthly_curve([(q.delivery_month, float(q.price)) for q in quotes])

        curve = ForwardCurve(
            commodity=commodity, as_of_date=as_of_date, status=CurveStatus.PUBLISHED
        )
        points = [
            CurvePoint(
                delivery_month=seg.delivery_month,
                # The piecewise-flat bootstrap is quant math (float); crosses into
                # exact arithmetic right here, at persistence -- same pattern as
                # RiskService.run_var's var_value.
                price=to_decimal(seg.price),
                tenor_bucket=seg.tenor_bucket,
            )
            for seg in segments
        ]
        return await self._repo.save_curve(curve, points)

    async def get_curve(self, curve_id: uuid.UUID) -> ForwardCurve:
        curve = await self._repo.get_curve(curve_id)
        if curve is None:
            raise NotFoundError("ForwardCurve", curve_id)
        return curve

    async def get_published_curve(self, commodity: Commodity, as_of_date: date) -> ForwardCurve:
        curve = await self._repo.get_published_curve(commodity, as_of_date)
        if curve is None:
            raise NotFoundError("ForwardCurve", f"{commodity}@{as_of_date}")
        return curve
