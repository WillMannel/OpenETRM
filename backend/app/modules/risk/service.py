import uuid
from datetime import date

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dates import month_range
from app.common.enums import LINEAR_TRADE_TYPES, BuySell, Commodity, TradeType, UserRole, VarMethod
from app.common.exceptions import ForbiddenError, NotFoundError
from app.common.lineage import get_code_version
from app.common.money import to_decimal
from app.core.config import get_settings
from app.modules.auth.models import User
from app.modules.entitlements.service import EntitlementService
from app.modules.limits.service import LimitService
from app.modules.market_data.repository import MarketDataRepository
from app.modules.risk.models import OptionGreeksResult, VarResult
from app.modules.risk.models import SensitivityResult as SensitivityResultRow
from app.modules.risk.models import StressResult as StressResultRow
from app.modules.risk.var.historical_sim import VarInput, historical_var
from app.modules.risk.var.monte_carlo import monte_carlo_var
from app.modules.risk.var.parametric import parametric_var
from app.modules.risk.var.pnl_attribution import PnlAttribution, TradeMonthSnapshot, attribute_pnl
from app.modules.risk.var.sensitivities import bucketed_delta_ladder
from app.modules.risk.var.stress import DEFAULT_SCENARIOS, StressScenario, run_stress_scenarios
from app.modules.trade_capture.models import Trade
from app.modules.trade_capture.repository import TradeRepository
from app.modules.valuation.options import black76_greeks
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
    ) -> tuple[pd.Series, list[str]]:
        """Every caller of this feeds the result into a single curve-valued number
        (VaR, a delta ladder, a stress test) for one commodity, so the trades behind it
        must be scoped to that same commodity -- otherwise an unrelated commodity's
        volume silently nets into the series (see test_multi_commodity_book.py).

        Also returns the exact `Trade.id`s (as strings) that were live and considered
        -- lineage for the caller to persist alongside its result, so "which trades
        produced this number" is answerable later even after those trades are
        amended/cancelled (see ARCHITECTURE.md's "Risk reproducibility and lineage")."""
        trades = await self._live_trades(book_id, commodity=commodity)
        trade_ids = [str(t.id) for t in trades]
        positions = self._valuation_service.build_positions(trades, as_of_date)
        if not positions:
            return pd.Series(dtype=float), trade_ids
        # float here, deliberately: this Series feeds numpy/pandas VaR and
        # bump-and-revalue quant math (historical_var, _curve_context.revalue), which
        # have no Decimal support and no benefit from it. p.net_volume itself is
        # still computed exactly in Decimal by build_positions -- this is the one
        # clean conversion point going *into* quant math, the mirror image of
        # app.common.money.to_decimal going the other way.
        series = pd.Series({p.delivery_month: float(p.net_volume) for p in positions})
        return series, trade_ids

    async def _price_panel(
        self, commodity: Commodity, as_of_date: date, window_days: int
    ) -> tuple[pd.DataFrame, list[str]]:
        """Also returns the exact `MarketDataPoint.id`s (as strings) that composed the
        panel -- without this, a later-arriving/backdated quote insert into the same
        historical window would silently change what a later "re-run" sees, with no
        way to detect after the fact that it happened (see ARCHITECTURE.md)."""
        quotes = await self._market_data_repo.price_history(commodity, as_of_date, window_days)
        point_ids = [str(q.id) for q in quotes]
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
            return pd.DataFrame(), point_ids
        pivoted = history.pivot_table(index="quote_date", columns="delivery_month", values="price")
        return pivoted, point_ids

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
        price_panel, market_data_point_ids = await self._price_panel(
            commodity, as_of_date, scenario_window_days
        )
        net_volume, trade_ids = await self._net_volume_by_month(book_id, as_of_date, commodity)

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
            commodity=commodity,
            as_of_date=as_of_date,
            confidence_level=confidence_level,
            horizon_days=1,
            method=method.value,
            scenario_window_days=scenario_window_days,
            var_value=var_value,
            trade_ids_used=trade_ids,
            market_data_point_ids=market_data_point_ids,
            code_version=get_code_version(),
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
        prices keyed by tenor bucket, a revalue_fn closing over the book's net volume
        per delivery month, and the exact trade ids that net volume was built from
        (lineage -- see _net_volume_by_month)."""
        curve = await self._market_data_repo.get_published_curve(commodity, as_of_date)
        if curve is None:
            raise NotFoundError("ForwardCurve", f"{commodity}@{as_of_date}")

        net_volume, trade_ids = await self._net_volume_by_month(book_id, as_of_date, commodity)
        price_by_bucket = {p.tenor_bucket: float(p.price) for p in curve.points}
        month_by_bucket = {p.tenor_bucket: p.delivery_month for p in curve.points}

        def revalue(curve_prices_by_bucket: dict[str, float]) -> float:
            total = 0.0
            for bucket, price in curve_prices_by_bucket.items():
                month = month_by_bucket[bucket]
                volume = float(net_volume.get(month, 0.0))
                total += volume * price
            return total

        return curve, price_by_bucket, revalue, trade_ids

    async def run_delta_ladder(
        self,
        book_id: uuid.UUID,
        as_of_date: date,
        commodity: Commodity,
        bump_size: float = 0.01,
        *,
        actor: User,
    ) -> tuple[uuid.UUID, list[SensitivityResultRow]]:
        await self._entitlement_service.assert_can_access_book(actor, book_id)
        curve, price_by_bucket, revalue, trade_ids = await self._curve_context(
            book_id, as_of_date, commodity
        )
        ladder = bucketed_delta_ladder(price_by_bucket, revalue, bump_size)
        code_version = get_code_version()

        results = [
            SensitivityResultRow(
                book_id=book_id,
                as_of_date=as_of_date,
                curve_id=curve.id,
                tenor_bucket=bucket.tenor_bucket,
                # Crosses from the bump-and-revalue quant math's float output into
                # exact arithmetic right at persistence -- see run_var's identical
                # treatment of var_value.
                delta_value=to_decimal(bucket.delta_value),
                bump_size=bucket.bump_size,
                trade_ids_used=trade_ids,
                code_version=code_version,
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
    ) -> list[StressResultRow]:
        """Persists one `StressResult` row per scenario -- previously this was an
        ephemeral computation with no database trace at all (see
        ARCHITECTURE.md's "Risk reproducibility and lineage")."""
        await self._entitlement_service.assert_can_access_book(actor, book_id)
        curve, price_by_bucket, revalue, trade_ids = await self._curve_context(
            book_id, as_of_date, commodity
        )
        # Resolved here (not left to run_stress_scenarios' own default) so the exact
        # scenario definitions actually used -- including shock_type/shock_value --
        # are available to persist alongside each result, not just its name.
        resolved_scenarios = scenarios if scenarios is not None else DEFAULT_SCENARIOS
        computed = run_stress_scenarios(price_by_bucket, revalue, resolved_scenarios)
        code_version = get_code_version()

        results = [
            StressResultRow(
                book_id=book_id,
                commodity=commodity,
                as_of_date=as_of_date,
                curve_id=curve.id,
                scenario_name=outcome.scenario_name,
                shock_type=scenario.shock_type,
                shock_value=scenario.shock_value,
                # Crosses from the bump-and-revalue quant math's float output into
                # exact arithmetic right at persistence -- see run_var's identical
                # treatment of var_value.
                pnl_impact=to_decimal(outcome.pnl_impact),
                trade_ids_used=trade_ids,
                code_version=code_version,
            )
            for scenario, outcome in zip(resolved_scenarios, computed, strict=True)
        ]
        for r in results:
            self._session.add(r)
        await self._session.commit()
        return results

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
    ) -> list[OptionGreeksResult]:
        """Per-trade Black-76 greeks for every live OPTION trade in the book, using the
        published curve's price at each trade's expiry-month bucket as the forward.
        Persists (and returns) one `OptionGreeksResult` row per trade -- previously
        this was an ephemeral computation with no database trace at all, and
        (uniquely among risk computations) consumes a config default
        (`risk_free_rate`) that was never otherwise recorded anywhere (see
        ARCHITECTURE.md's "Risk reproducibility and lineage")."""
        await self._entitlement_service.assert_can_access_book(actor, book_id)
        curve = await self._market_data_repo.get_published_curve(commodity, as_of_date)
        if curve is None:
            raise NotFoundError("ForwardCurve", f"{commodity}@{as_of_date}")
        curve_price_by_month = {p.delivery_month: float(p.price) for p in curve.points}

        rate = get_settings().risk_free_rate
        rate_decimal = to_decimal(rate)
        code_version = get_code_version()
        results: list[OptionGreeksResult] = []
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
            result = OptionGreeksResult(
                trade_id=trade.id,
                book_id=book_id,
                commodity=commodity,
                as_of_date=as_of_date,
                curve_id=curve.id,
                delta=greeks.delta,
                gamma=greeks.gamma,
                vega=greeks.vega,
                theta=greeks.theta,
                risk_free_rate_used=rate_decimal,
                code_version=code_version,
            )
            self._session.add(result)
            results.append(result)
        if results:
            # No per-row refresh() loop here (see task P1-9, ARCHITECTURE.md's
            # "Scale and performance") -- every field OptionGreeksRead actually
            # exposes is already set on `result` before commit (id is a
            # client-side default, everything else was computed above); the only
            # server-generated column is computed_at, which isn't in the response.
            # A refresh-per-row here would be N sequential round trips for a book
            # with N live option trades, for zero information gain.
            await self._session.commit()
        return results

    async def get_var_result(self, var_result_id: uuid.UUID, *, actor: User) -> VarResult:
        """Entitlement-checked fetch of a previously-persisted VarResult by id --
        without this, GET /risk/var/{id} would let any authenticated user read any
        book's VaR by guessing/observing its id, bypassing the exact desk-separation
        `run_var` enforces on write (see ARCHITECTURE.md's "Book-level entitlements"
        and "Internal security-review pass" sections)."""
        result = await self._session.get(VarResult, var_result_id)
        if result is None:
            raise NotFoundError("VarResult", str(var_result_id))
        await self._assert_can_access_risk_scope(actor, result.book_id)
        return result

    async def get_stress_result(
        self, stress_result_id: uuid.UUID, *, actor: User
    ) -> StressResultRow:
        """See get_var_result's docstring -- same gap, same fix, for stress-test
        results. `StressResult.book_id` is never null (unlike VarResult's), but
        `_assert_can_access_risk_scope` handles both correctly either way."""
        result = await self._session.get(StressResultRow, stress_result_id)
        if result is None:
            raise NotFoundError("StressResult", str(stress_result_id))
        await self._assert_can_access_risk_scope(actor, result.book_id)
        return result

    async def get_option_greeks_result(
        self, result_id: uuid.UUID, *, actor: User
    ) -> OptionGreeksResult:
        """See get_var_result's docstring -- same gap, same fix, for option-greeks
        results."""
        result = await self._session.get(OptionGreeksResult, result_id)
        if result is None:
            raise NotFoundError("OptionGreeksResult", str(result_id))
        await self._assert_can_access_risk_scope(actor, result.book_id)
        return result
