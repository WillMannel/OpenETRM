import uuid
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dates import month_range
from app.common.enums import LIVE_TRADE_STATUSES, BuySell, Commodity, VarMethod
from app.common.exceptions import NotFoundError
from app.modules.market_data.repository import MarketDataRepository
from app.modules.risk.models import SensitivityResult, VarResult
from app.modules.risk.var.historical_sim import VarInput, historical_var
from app.modules.risk.var.monte_carlo import monte_carlo_var
from app.modules.risk.var.parametric import parametric_var
from app.modules.risk.var.pnl_attribution import PnlAttribution, TradeMonthSnapshot, attribute_pnl
from app.modules.risk.var.sensitivities import bucketed_delta_ladder
from app.modules.risk.var.stress import StressResult, StressScenario, run_stress_scenarios
from app.modules.trade_capture.models import Trade
from app.modules.valuation.service import ValuationService

_VAR_METHODS = {
    VarMethod.HISTORICAL_SIM: historical_var,
    VarMethod.PARAMETRIC: parametric_var,
    VarMethod.MONTE_CARLO: monte_carlo_var,
}


class RiskService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._market_data_repo = MarketDataRepository(session)
        self._valuation_service = ValuationService(session)

    async def _live_trades(self, book_id: uuid.UUID | None) -> list[Trade]:
        stmt = select(Trade).where(Trade.status.in_([s.value for s in LIVE_TRADE_STATUSES]))
        if book_id is not None:
            stmt = stmt.where(Trade.book_id == book_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _net_volume_by_month(self, book_id: uuid.UUID | None, as_of_date: date) -> pd.Series:
        trades = await self._live_trades(book_id)
        positions = self._valuation_service.build_positions(trades, as_of_date)
        if not positions:
            return pd.Series(dtype=float)
        return pd.Series({p.delivery_month: p.net_volume for p in positions})

    async def _price_panel(
        self, commodity: Commodity, as_of_date: date, window_days: int
    ) -> pd.DataFrame:
        quotes = await self._market_data_repo.price_history(commodity, as_of_date, window_days)
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
            return pd.DataFrame()
        return history.pivot_table(index="quote_date", columns="delivery_month", values="price")

    async def run_var(
        self,
        book_id: uuid.UUID | None,
        as_of_date: date,
        commodity: Commodity,
        confidence_level: int,
        scenario_window_days: int,
        method: VarMethod = VarMethod.HISTORICAL_SIM,
    ) -> VarResult:
        price_panel = await self._price_panel(commodity, as_of_date, scenario_window_days)
        net_volume = await self._net_volume_by_month(book_id, as_of_date)

        var_fn = _VAR_METHODS[method]
        var_value = var_fn(
            VarInput(price_history=price_panel, net_volume_by_month=net_volume), confidence_level
        )

        result = VarResult(
            book_id=book_id,
            as_of_date=as_of_date,
            confidence_level=confidence_level,
            horizon_days=1,
            method=method.value,
            scenario_window_days=scenario_window_days,
            var_value=var_value,
        )
        self._session.add(result)
        await self._session.commit()
        await self._session.refresh(result)
        return result

    async def _curve_context(
        self, book_id: uuid.UUID | None, as_of_date: date, commodity: Commodity
    ):
        """Shared setup for delta-ladder and stress test: the published curve, its
        prices keyed by tenor bucket, and a revalue_fn closing over the book's net
        volume per delivery month."""
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

        return curve, price_by_bucket, revalue

    async def run_delta_ladder(
        self, book_id: uuid.UUID, as_of_date: date, commodity: Commodity, bump_size: float = 0.01
    ) -> tuple[uuid.UUID, list[SensitivityResult]]:
        curve, price_by_bucket, revalue = await self._curve_context(book_id, as_of_date, commodity)
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

    async def run_stress_test(
        self,
        book_id: uuid.UUID,
        as_of_date: date,
        commodity: Commodity,
        scenarios: list[StressScenario] | None = None,
    ) -> list[StressResult]:
        _curve, price_by_bucket, revalue = await self._curve_context(book_id, as_of_date, commodity)
        return run_stress_scenarios(price_by_bucket, revalue, scenarios)

    async def compute_pnl_attribution(
        self, book_id: uuid.UUID, prior_date: date, current_date: date, commodity: Commodity
    ) -> PnlAttribution:
        prior_curve = await self._market_data_repo.get_published_curve(commodity, prior_date)
        current_curve = await self._market_data_repo.get_published_curve(commodity, current_date)
        if current_curve is None:
            raise NotFoundError("ForwardCurve", f"{commodity}@{current_date}")

        prior_prices = (
            {p.delivery_month: float(p.price) for p in prior_curve.points} if prior_curve else {}
        )
        current_prices = {p.delivery_month: float(p.price) for p in current_curve.points}

        trades = await self._live_trades(book_id)
        snapshots = [
            TradeMonthSnapshot(
                delivery_month=month,
                signed_volume=float(t.volume) if t.buy_sell == BuySell.BUY else -float(t.volume),
                fixed_price=float(t.fixed_price),
                trade_date=t.trade_date,
            )
            for t in trades
            for month in month_range(t.delivery_start_month, t.delivery_end_month)
        ]
        return attribute_pnl(snapshots, prior_date, current_date, prior_prices, current_prices)
