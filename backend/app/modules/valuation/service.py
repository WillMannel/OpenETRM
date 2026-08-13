"""Mark-to-market valuation: aggregate trades into positions, value each position's
remaining delivery months against a published forward curve.

Sign convention: BUY is a long position (positive volume), SELL is short (negative
volume). MTM value of a position = net_volume * (curve_price - avg_fixed_price) for a
swap/forward, i.e. the standard fixed-for-floating settlement payoff.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dates import month_range
from app.common.enums import LINEAR_TRADE_TYPES, BuySell, Commodity, TradeType
from app.common.exceptions import NotFoundError
from app.common.lineage import get_code_version
from app.common.money import to_decimal
from app.core.config import get_settings
from app.modules.auth.models import User
from app.modules.entitlements.service import EntitlementService
from app.modules.market_data.repository import MarketDataRepository
from app.modules.trade_capture.models import Trade
from app.modules.trade_capture.repository import TradeRepository
from app.modules.valuation.models import Position, ValuationResult, ValuationRun
from app.modules.valuation.options import black76_price


@dataclass(frozen=True)
class MarkToMarketComputation:
    """The pure result of a mark-to-market computation: `Position`/`ValuationResult`
    objects built in memory, not yet added to a session or given a `run_id`. Returned
    by `ValuationService.mark_to_market` (used by the read-only GET endpoint, which
    must never write) and consumed by `persist_valuation_run` (used by the write
    endpoint that deliberately creates a durable, reportable snapshot)."""

    curve_id: uuid.UUID
    positions: list[Position]
    results: list[ValuationResult]
    # Lineage: the exact Trade.id's (as strings) live at computation time -- see
    # ARCHITECTURE.md's "Risk reproducibility and lineage". Populated by
    # compute_mark_to_market, persisted onto ValuationRun by persist_valuation_run.
    trade_ids_used: list[str]


def _enum_value(v: object) -> object:
    """ORM attributes on these str-mixin-enum columns come back as a plain `str` after
    a DB round trip, but as the actual enum instance on a freshly-constructed object --
    handle both uniformly."""
    return v.value if hasattr(v, "value") else v


class ValuationService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._market_data_repo = MarketDataRepository(session)
        self._trade_repo = TradeRepository(session)
        self._entitlement_service = EntitlementService(session)

    async def _trades_for_book(self, book_id: uuid.UUID, commodity: Commodity) -> list[Trade]:
        """Only LIVE_TRADE_STATUSES count -- a draft (NEW), superseded (AMENDED), or
        CANCELLED trade must not move a position or a book's P&L. Scoped to a single
        commodity: a book that holds both gas and power must never have those legs
        netted into the same position (see test_multi_commodity_book.py)."""
        return await self._trade_repo.list_live(book_id, commodity=commodity)

    def build_positions(self, trades: list[Trade], as_of_date: date) -> list[Position]:
        """Roll LINEAR_TRADE_TYPES (SWAP/FORWARD) trades up into net volume / average
        fixed price per (commodity, delivery month). OPTION trades are excluded --
        their payoff isn't linear in volume the way a swap/forward's is (different
        trades can carry different strikes/volatilities), so they're valued
        individually instead; see price_option_trade / mark_to_market.
        REC/EMISSIONS_ALLOWANCE trades are excluded too -- v1 has no curve-based
        valuation for them at all (see common.enums.LINEAR_TRADE_TYPES).

        The bucket key is (commodity, month), not just month -- callers are still
        responsible for passing in trades already scoped to one commodity where that
        matters (a single curve-valued number must never span commodities), but this
        grain keeps that true even if a caller passes a mixed-commodity trade list."""
        buckets: dict[tuple[str, date], list[Trade]] = defaultdict(list)
        for trade in trades:
            if trade.trade_type not in LINEAR_TRADE_TYPES:
                continue
            commodity_key = str(_enum_value(trade.commodity))
            for month in month_range(trade.delivery_start_month, trade.delivery_end_month):
                buckets[(commodity_key, month)].append(trade)

        positions: list[Position] = []
        sorted_buckets = sorted(buckets.items(), key=lambda kv: kv[0][1])
        for (_commodity_key, month), month_trades in sorted_buckets:
            volume_units = {_enum_value(t.volume_unit) for t in month_trades}
            if len(volume_units) > 1:
                # Same commodity, same month, but different volume units -- summing
                # raw volumes would silently blend incompatible units (e.g. MMBtu and
                # Dth). This should never happen given how commodities map to units
                # today, but fail loudly rather than fabricate a number if it ever does.
                raise ValueError(
                    f"mixed volume units {volume_units} within one position bucket "
                    f"({_commodity_key}, {month}) -- refusing to net incompatible units"
                )
            # Decimal arithmetic throughout -- t.volume/t.fixed_price are already
            # Decimal (Numeric-backed columns) on any real, ORM-loaded Trade; the
            # to_decimal() calls below are a no-op for those and only matter for a
            # Trade built in memory with plain int/float literals (as several unit
            # tests do). Either way, this sum/weighted-average is exactly the kind of
            # computation, over an unbounded number of trades, where float summation
            # silently accumulates rounding error -- casting to float here (as this
            # used to) buys nothing and throws away the exactness the DB column
            # already guarantees.
            signed_volumes = [
                (to_decimal(t.volume) if t.buy_sell == BuySell.BUY else -to_decimal(t.volume))
                for t in month_trades
            ]
            net_volume = sum(signed_volumes, Decimal(0))
            total_abs_volume = sum((abs(v) for v in signed_volumes), Decimal(0)) or Decimal(1)
            # fixed_price is only ever null for OPTION trades, already filtered out of
            # month_trades above -- the `or Decimal(0)` is just to satisfy the type checker.
            weighted_prices = [
                abs(v) * to_decimal(t.fixed_price or 0)
                for v, t in zip(signed_volumes, month_trades, strict=True)
            ]
            avg_price = sum(weighted_prices, Decimal(0)) / total_abs_volume

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

    def price_option_trade(
        self,
        trade: Trade,
        curve_price_by_month: dict[date, Decimal],
        as_of_date: date,
        curve_id: uuid.UUID,
    ) -> ValuationResult | None:
        """Per-trade (not netted) valuation for an OPTION trade via Black-76. Returns
        None if the curve has no quote for the trade's expiry-month bucket
        (delivery_start_month) rather than fabricating a value."""
        forward = curve_price_by_month.get(trade.delivery_start_month)
        if forward is None:
            return None

        time_to_expiry_years = max((trade.delivery_start_month - as_of_date).days, 0) / 365.0
        risk_free_rate = get_settings().risk_free_rate
        # Black-76 is quant math (numpy/scipy), not exact bookkeeping -- float in,
        # float out is correct here. See app.common.money's module docstring.
        option_value = black76_price(
            forward=float(forward),
            strike=float(trade.strike_price),  # type: ignore[arg-type]
            volatility=float(trade.option_volatility),  # type: ignore[arg-type]
            time_to_expiry_years=time_to_expiry_years,
            risk_free_rate=risk_free_rate,
            option_type=trade.option_type,  # type: ignore[arg-type]
        )
        trade_volume = to_decimal(trade.volume)
        signed_volume = trade_volume if trade.buy_sell == BuySell.BUY else -trade_volume
        # Cross back into exact arithmetic the moment Black-76's float result is
        # available -- everything downstream (persisted mtm_value/unrealized_pnl) is
        # Decimal from here on.
        mtm_value = signed_volume * to_decimal(option_value)
        # The premium was already paid/received at trade_date; unrealized P&L nets it
        # out of the option's current fair value, the same way a swap's unrealized P&L
        # nets the curve price against the fixed price it was struck at.
        unrealized = mtm_value - signed_volume * to_decimal(trade.premium)  # type: ignore[arg-type]
        return ValuationResult(
            trade_id=trade.id,
            book_id=trade.book_id,
            commodity=_enum_value(trade.commodity),
            delivery_month=trade.delivery_start_month,
            as_of_date=as_of_date,
            curve_id=curve_id,
            mtm_value=mtm_value,
            realized_pnl=0,
            unrealized_pnl=unrealized,
            # Lineage (see ARCHITECTURE.md): the single global risk_free_rate
            # config default that priced this option, otherwise never recorded
            # anywhere -- if it's ever changed, this result stays provably
            # attributable to the rate actually in effect when it was computed.
            risk_free_rate_used=to_decimal(risk_free_rate),
        )

    async def compute_mark_to_market(
        self, book_id: uuid.UUID, as_of_date: date, commodity: Commodity, actor: User
    ) -> MarkToMarketComputation:
        """Pure computation: builds `Position`/`ValuationResult` objects in memory and
        returns them -- never calls `session.add`/`commit`. This is the piece that
        used to be entangled with persistence inside the old `mark_to_market`, which a
        read-only GET endpoint called on every request; calling this method has no
        side effects no matter how many times it's called (see
        tests/integration/test_valuation_run_idempotency.py). Still checks entitlement
        (see app.modules.entitlements) even though it's a pure read -- "no side
        effects" doesn't mean "no access control"."""
        await self._entitlement_service.assert_can_access_book(actor, book_id)
        curve = await self._market_data_repo.get_published_curve(commodity, as_of_date)
        if curve is None:
            raise NotFoundError("ForwardCurve", f"{commodity}@{as_of_date}")

        trades = await self._trades_for_book(book_id, commodity)
        positions = self.build_positions(trades, as_of_date)
        curve_price_by_month = {p.delivery_month: p.price for p in curve.points}

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
                    commodity=_enum_value(position.commodity),
                    delivery_month=position.delivery_month,
                    as_of_date=as_of_date,
                    curve_id=curve.id,
                    mtm_value=unrealized,
                    realized_pnl=0,
                    unrealized_pnl=unrealized,
                )
            )

        for trade in trades:
            if trade.trade_type != TradeType.OPTION:
                continue
            option_result = self.price_option_trade(
                trade, curve_price_by_month, as_of_date, curve.id
            )
            if option_result is None:
                continue
            results.append(option_result)

        return MarkToMarketComputation(
            curve_id=curve.id,
            positions=positions,
            results=results,
            trade_ids_used=[str(t.id) for t in trades],
        )

    async def mark_to_market(
        self, book_id: uuid.UUID, as_of_date: date, commodity: Commodity, actor: User
    ) -> tuple[list[Position], list[ValuationResult]]:
        """Back-compat pure wrapper around compute_mark_to_market -- computes but does
        NOT persist. This is what the read-only GET /positions/{book_id}/pnl endpoint
        calls: safe to call any number of times, never writes a row."""
        computation = await self.compute_mark_to_market(book_id, as_of_date, commodity, actor)
        return computation.positions, computation.results

    async def persist_valuation_run(
        self,
        book_id: uuid.UUID,
        as_of_date: date,
        commodity: Commodity,
        actor: User,
    ) -> tuple[ValuationRun, MarkToMarketComputation]:
        """The deliberate write path: computes fresh (via compute_mark_to_market) and
        persists a new ValuationRun plus its Position/ValuationResult rows in one
        transaction. Each call creates a new run rather than updating a prior one --
        re-running (after a late trade, a curve republish, an EOD close) is expected
        and each run is kept for history/audit; reporting reads the latest run only
        (see v_positions_flat/v_valuation_results_flat and ExportService). Returns the
        persisted run alongside the computation so callers don't need a second query
        to render the numbers just written."""
        computation = await self.compute_mark_to_market(book_id, as_of_date, commodity, actor)

        run = ValuationRun(
            book_id=book_id,
            commodity=commodity,
            as_of_date=as_of_date,
            curve_id=computation.curve_id,
            computed_by_user_id=actor.id,
            trade_ids_used=computation.trade_ids_used,
            code_version=get_code_version(),
        )
        self._session.add(run)
        await self._session.flush()  # assigns run.id without ending the transaction

        for position in computation.positions:
            position.run_id = run.id
            self._session.add(position)
        for result in computation.results:
            result.run_id = run.id
            self._session.add(result)

        await self._session.commit()
        await self._session.refresh(run)
        return run, computation
