import uuid
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import Commodity
from app.common.exceptions import NotFoundError
from app.modules.market_data.repository import MarketDataRepository
from app.modules.risk.models import SensitivityResult, VarResult
from app.modules.risk.var.historical_sim import VarInput, historical_var
from app.modules.risk.var.sensitivities import bucketed_delta_ladder
from app.modules.trade_capture.models import Trade
from app.modules.valuation.service import ValuationService


class RiskService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._market_data_repo = MarketDataRepository(session)
        self._valuation_service = ValuationService(session)

    async def _net_volume_by_month(self, book_id: uuid.UUID | None, as_of_date: date) -> pd.Series:
        stmt = select(Trade)
        if book_id is not None:
            stmt = stmt.where(Trade.book_id == book_id)
        result = await self._session.execute(stmt)
        trades = list(result.scalars().all())
        positions = self._valuation_service.build_positions(trades, as_of_date)
        if not positions:
            return pd.Series(dtype=float)
        return pd.Series({p.delivery_month: p.net_volume for p in positions})

    async def run_var(
        self,
        book_id: uuid.UUID | None,
        as_of_date: date,
        commodity: Commodity,
        confidence_level: int,
        scenario_window_days: int,
    ) -> VarResult:
        quotes = await self._market_data_repo.price_history(
            commodity, as_of_date, scenario_window_days
        )
        history = pd.DataFrame(
            [
                {
                    "quote_date": q.quote_date,
                    "delivery_month": q.delivery_month,
                    "price": float(q.price),
                }
                for q in quotes
            ]
        )
        if history.empty:
            price_panel = pd.DataFrame()
        else:
            price_panel = history.pivot_table(
                index="quote_date", columns="delivery_month", values="price"
            )

        net_volume = await self._net_volume_by_month(book_id, as_of_date)
        var_value = historical_var(
            VarInput(price_history=price_panel, net_volume_by_month=net_volume), confidence_level
        )

        result = VarResult(
            book_id=book_id,
            as_of_date=as_of_date,
            confidence_level=confidence_level,
            horizon_days=1,
            method="HISTORICAL_SIM",
            scenario_window_days=scenario_window_days,
            var_value=var_value,
        )
        self._session.add(result)
        await self._session.commit()
        await self._session.refresh(result)
        return result

    async def run_delta_ladder(
        self, book_id: uuid.UUID, as_of_date: date, commodity: Commodity, bump_size: float = 0.01
    ) -> tuple[uuid.UUID, list[SensitivityResult]]:
        curve = await self._market_data_repo.get_published_curve(commodity, as_of_date)
        if curve is None:
            raise NotFoundError("ForwardCurve", f"{commodity}@{as_of_date}")

        net_volume = await self._net_volume_by_month(book_id, as_of_date)
        price_by_bucket = {p.tenor_bucket: float(p.price) for p in curve.points}
        month_by_bucket = {p.tenor_bucket: p.delivery_month for p in curve.points}

        def revalue(curve_prices_by_bucket: dict[str, float]) -> float:
            total = 0.0
            for bucket, price in curve_prices_by_bucket.items():
                month = month_by_bucket[bucket]
                volume = float(net_volume.get(month, 0.0))
                total += volume * price
            return total

        ladder = bucketed_delta_ladder(price_by_bucket, revalue, bump_size)

        results = [
            SensitivityResult(
                book_id=book_id,
                as_of_date=as_of_date,
                curve_id=curve.id,
                tenor_bucket=bucket.tenor_bucket,
                delta_value=bucket.delta_value,
                bump_size=bucket.bump_size,
            )
            for bucket in ladder
        ]
        for r in results:
            self._session.add(r)
        await self._session.commit()
        return curve.id, results
