import uuid
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import Commodity, CurveStatus
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.common.money import to_decimal
from app.modules.market_data.curve_builder.bootstrapper import bootstrap_monthly_curve
from app.modules.market_data.models import CurvePoint, ForwardCurve, MarketDataPoint
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.schemas import MarketDataPointCreate


class MarketDataService:
    def __init__(self, session: AsyncSession):
        self._repo = MarketDataRepository(session)

    async def add_quote(self, payload: MarketDataPointCreate) -> MarketDataPoint:
        """(commodity, quote_date, delivery_month) is a quote's natural key -- see
        `uq_market_data_point_commodity_quote_delivery` and ARCHITECTURE.md's "Risk
        reproducibility and lineage" section for why a duplicate isn't safe to allow:
        which of two same-day quotes "the" historical price window picks would
        otherwise be order-dependent, not reproducible. Checked proactively (not just
        left to the DB constraint) so a duplicate submission gets a clear 409, not a
        raw IntegrityError surfacing as a 500."""
        existing = await self._repo.get_by_natural_key(
            payload.commodity, payload.quote_date, payload.delivery_month
        )
        if existing is not None:
            raise ValidationFailedError(
                f"a quote for {payload.commodity.value} already exists at "
                f"quote_date={payload.quote_date} delivery_month={payload.delivery_month} "
                "-- market data points are immutable; there is no correction/revision "
                "flow yet (see FUTURE_WORK.md)"
            )
        try:
            return await self._repo.add_quote(MarketDataPoint(**payload.model_dump()))
        except IntegrityError as exc:
            # The proactive check above has a check-then-act race: two concurrent
            # submissions of the same quote can both pass it before either commits.
            # uq_market_data_point_commodity_quote_delivery is what actually closes
            # that race -- this translates the loser's raw IntegrityError into the
            # same clean error the proactive check raises, rather than a 500.
            await self._repo.rollback()
            raise ValidationFailedError(
                f"a quote for {payload.commodity.value} already exists at "
                f"quote_date={payload.quote_date} delivery_month={payload.delivery_month}"
            ) from exc

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
