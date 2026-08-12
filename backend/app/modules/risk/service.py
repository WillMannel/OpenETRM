import uuid
from datetime import date

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dates import month_range
from app.common.enums import LINEAR_TRADE_TYPES, BuySell, Commodity, TradeType, UserRole, VarMethod
from app.common.exceptions import ForbiddenError, NotFoundError
from app.common.money import to_decimal
from app.core.config import get_settings
from app.modules.auth.models import User
from app.modules.entitlements.service import EntitlementService
from app.modules.limits.service import LimitService
from app.modules.market_data.repository import MarketDataRepository
from app.modules.risk.models import SensitivityResult, VarResult
from app.modules.risk.var.historical_sim import VarInput, historical_var
from app.modules.risk.var.monte_carlo import monte_carlo_var
from app.modules.risk.var.parametric import parametric_var
from app.modules.risk.var.pnl_attribution import PnlAttribution, TradeMonthSnapshot, attribute_pnl
from app.modules.risk.var.sensitivities import bucketed_delta_ladder
from app.modules.risk.var.stress import StressResult, StressScenario, run_stress_scenarios
from app.modules.trade_capture.models import Trade
from app.modules.trade_capture.repository import TradeRepository
from app.modules.valuation.options import OptionGreeks, black76_greeks
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
        self._limit_service = LimitService(session)
        self._trade_repo = TradeRepository(session)
        self._entitlement_service = EntitlementService(session)

    async def _assert_can_access_risk_scope(self, actor: User, book_id: uuid.UUID | None) -> None:
        """book_id=None is a portfolio-wide run across every book -- there's no single
        book to check entitlement against, and filtering the trades behind it down to
        "only the caller's accessible books" would silently produce a different,
        smaller-scope number under the same "portfolio-wide" label, which is worse
        than just refusing. So a portfolio-wide run requires ADMIN outright."""
        if book_id is None:
            role = UserRole(actor.role.value if hasattr(actor.role, "value") else actor.role)
            if role != UserRole.ADMIN:
                raise ForbiddenError(
                    "a portfolio-wide (book_id=None) risk run requires the ADMIN role"
                )
            return
        await self._entitlement_service.assert_can_access_book(actor, book_id)

    async def _live_trades(
        self, book_id: uuid.UUID | None, commodity: Commodity | None = None
    ) -> list[Trade]:
        return await self._trade_repo.list_live(book_id, commodity=commodity)

    async def _net_volume_by_month(
        self, book_id: uuid.UUID | None, as_of_date: date, commodity: Commodity
    ) -> pd.Series:
        """Every caller of this feeds the result into a single curve-valued number
        (VaR, a delta ladder, a stress test) for one commodity, so the trades behind it
        must be scoped to that same commodity -- otherwise an unrelated commodity's
        volume silently nets into the series (see test_multi_commodity_book.py)."""
        trades = await self._live_trades(book_id, commodity=commodity)
        positions = self._valuation_service.build_positions(trades, as_of_date)
        if not positions:
            return pd.Series(dtype=float)
        # float here, deliberately: this Series feeds numpy/pandas VaR and
        # bump-and-revalue quant math (historical_var, _curve_context.revalue), which
        # have no Decimal support and no benefit from it. p.net_volume itself is
        # still computed exactly in Decimal by build_positions -- this is the one
        # clean conversion point going *into* quant math, the mirror image of
        # app.common.money.to_decimal going the other way.
        return pd.Series({p.delivery_month: float(p.net_volume) for p in positions})

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
        *,
        actor: User,
    ) -> VarResult:
        await self._assert_can_access_risk_scope(actor, book_id)
        price_panel = await self._price_panel(commodity, as_of_date, scenario_window_days)
        net_volume = await self._net_volume_by_month(book_id, as_of_date, commodity)

        var_fn = _VAR_METHODS[method]
        # Historical-sim/parametric/Monte Carlo VaR is quant math (numpy/pandas),
        # float in, float out -- correct to leave as-is. var_value crosses into exact
        # arithmetic right here, the moment it's about to be persisted/compared
        # against a limit threshold.
        var_value = to_decimal(
            var_fn(
                VarInput(price_history=price_panel, net_volume_by_month=net_volume),
                confidence_level,
            )
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

        # Non-blocking: a VAR limit breach is recorded/audited but never suppresses the
        # result -- a risk report must always be able to show an over-limit number.
        await self._limit_service.check_var_limit(
            book_id, commodity, confidence_level, var_value, as_of_date, actor
        )
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

        net_volume = await self._net_volume_by_month(book_id, as_of_date, commodity)
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
        self,
        book_id: uuid.UUID,
        as_of_date: date,
        commodity: Commodity,
        bump_size: float = 0.01,
        *,
        actor: User,
    ) -> tuple[uuid.UUID, list[SensitivityResult]]:
        await self._entitlement_service.assert_can_access_book(actor, book_id)
        curve, price_by_bucket, revalue = await self._curve_context(book_id, as_of_date, commodity)
        ladder = bucketed_delta_ladder(price_by_bucket, revalue, bump_size)

        results = [
            SensitivityResult(
                book_id=book_id,
                as_of_date=as_of_date,
                curve_id=curve.id,
                tenor_bucket=bucket.tenor_bucket,
                # Crosses from the bump-and-revalue quant math's float output into
                # exact arithmetic right at persistence -- see run_var's identical
                # treatment of var_value.
                delta_value=to_decimal(bucket.delta_value),
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
        *,
        actor: User,
    ) -> list[StressResult]:
        await self._entitlement_service.assert_can_access_book(actor, book_id)
        _curve, price_by_bucket, revalue = await self._curve_context(book_id, as_of_date, commodity)
        return run_stress_scenarios(price_by_bucket, revalue, scenarios)

    async def compute_pnl_attribution(
        self,
        book_id: uuid.UUID,
        prior_date: date,
        current_date: date,
        commodity: Commodity,
        *,
        actor: User,
    ) -> PnlAttribution:
        await self._entitlement_service.assert_can_access_book(actor, book_id)
        prior_curve = await self._market_data_repo.get_published_curve(commodity, prior_date)
        current_curve = await self._market_data_repo.get_published_curve(commodity, current_date)
        if current_curve is None:
            raise NotFoundError("ForwardCurve", f"{commodity}@{current_date}")

        # Decimal, not float -- this feeds attribute_pnl's trade-by-trade P&L
        # summation, the exact same unbounded-summation-over-many-trades shape as
        # ValuationService.build_positions (curve/trade prices here are already
        # Decimal at the ORM boundary; no cast needed to keep them that way).
        prior_prices = (
            {p.delivery_month: p.price for p in prior_curve.points} if prior_curve else {}
        )
        current_prices = {p.delivery_month: p.price for p in current_curve.points}

        trades = await self._live_trades(book_id, commodity=commodity)
        snapshots = [
            TradeMonthSnapshot(
                delivery_month=month,
                # to_decimal is a no-op for a real (ORM-loaded) Trade's already-Decimal
                # volume/fixed_price -- see ValuationService.build_positions's
                # identical comment for why it's still needed here.
                signed_volume=(
                    to_decimal(t.volume) if t.buy_sell == BuySell.BUY else -to_decimal(t.volume)
                ),
                fixed_price=to_decimal(t.fixed_price),  # type: ignore[arg-type]
                trade_date=t.trade_date,
            )
            for t in trades
            # non-linear/uncurved payoff (and fixed_price is null for some of these);
            # excluded, same as ValuationService.build_positions
            if t.trade_type in LINEAR_TRADE_TYPES
            for month in month_range(t.delivery_start_month, t.delivery_end_month)
        ]
        return attribute_pnl(snapshots, prior_date, current_date, prior_prices, current_prices)

    async def compute_option_greeks(
        self, book_id: uuid.UUID, as_of_date: date, commodity: Commodity, *, actor: User
    ) -> list[tuple[Trade, OptionGreeks]]:
        """Per-trade Black-76 greeks for every live OPTION trade in the book, using the
        published curve's price at each trade's expiry-month bucket as the forward."""
        await self._entitlement_service.assert_can_access_book(actor, book_id)
        curve = await self._market_data_repo.get_published_curve(commodity, as_of_date)
        if curve is None:
            raise NotFoundError("ForwardCurve", f"{commodity}@{as_of_date}")
        curve_price_by_month = {p.delivery_month: float(p.price) for p in curve.points}

        rate = get_settings().risk_free_rate
        results: list[tuple[Trade, OptionGreeks]] = []
        for trade in await self._live_trades(book_id, commodity=commodity):
            if trade.trade_type != TradeType.OPTION:
                continue
            forward = curve_price_by_month.get(trade.delivery_start_month)
            if forward is None:
                continue
            time_to_expiry_years = max((trade.delivery_start_month - as_of_date).days, 0) / 365.0
            greeks = black76_greeks(
                forward=forward,
                strike=float(trade.strike_price),  # type: ignore[arg-type]
                volatility=float(trade.option_volatility),  # type: ignore[arg-type]
                time_to_expiry_years=time_to_expiry_years,
                risk_free_rate=rate,
                option_type=trade.option_type,  # type: ignore[arg-type]
            )
            results.append((trade, greeks))
        return results
