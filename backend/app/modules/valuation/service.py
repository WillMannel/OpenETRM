"""Mark-to-market valuation: aggregate trades into positions, value each position's
remaining delivery months against a published forward curve.

Sign convention: BUY is a long position (positive volume), SELL is short (negative
volume). MTM value of a position = net_volume * (curve_price - avg_fixed_price) for a
swap/forward, i.e. the standard fixed-for-floating settlement payoff.
"""

import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dates import month_range
from app.common.enums import LIVE_TRADE_STATUSES, BuySell, Commodity, TradeType
from app.common.exceptions import NotFoundError
from app.core.config import get_settings
from app.modules.market_data.repository import MarketDataRepository
from app.modules.trade_capture.models import Trade
from app.modules.valuation.models import Position, ValuationResult
from app.modules.valuation.options import black76_price


class ValuationService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._market_data_repo = MarketDataRepository(session)

    async def _trades_for_book(self, book_id: uuid.UUID) -> list[Trade]:
        """Only LIVE_TRADE_STATUSES count -- a draft (NEW), superseded (AMENDED), or
        CANCELLED trade must not move a position or a book's P&L."""
        stmt = select(Trade).where(
            Trade.book_id == book_id, Trade.status.in_([s.value for s in LIVE_TRADE_STATUSES])
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def build_positions(self, trades: list[Trade], as_of_date: date) -> list[Position]:
        """Roll linear (SWAP/FORWARD) trades up into net volume / average fixed price
        per delivery month. OPTION trades are excluded -- their payoff isn't linear in
        volume the way a swap/forward's is (different trades can carry different
        strikes/volatilities), so they're valued individually instead; see
        price_option_trade / mark_to_market."""
        buckets: dict[date, list[Trade]] = defaultdict(list)
        for trade in trades:
            if trade.trade_type == TradeType.OPTION:
                continue
            for month in month_range(trade.delivery_start_month, trade.delivery_end_month):
                buckets[month].append(trade)

        positions: list[Position] = []
        for month, month_trades in sorted(buckets.items()):
            signed_volumes = [
                (float(t.volume) if t.buy_sell == BuySell.BUY else -float(t.volume))
                for t in month_trades
            ]
            net_volume = sum(signed_volumes)
            total_abs_volume = sum(abs(v) for v in signed_volumes) or 1.0
            # fixed_price is only ever null for OPTION trades, already filtered out of
            # month_trades above -- the `or 0.0` is just to satisfy the type checker.
            weighted_prices = [
                abs(v) * float(t.fixed_price or 0.0)
                for v, t in zip(signed_volumes, month_trades, strict=True)
            ]
            avg_price = sum(weighted_prices) / total_abs_volume

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
        curve_price_by_month: dict[date, float],
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
        option_value = black76_price(
            forward=forward,
            strike=float(trade.strike_price),  # type: ignore[arg-type]
            volatility=float(trade.option_volatility),  # type: ignore[arg-type]
            time_to_expiry_years=time_to_expiry_years,
            risk_free_rate=get_settings().risk_free_rate,
            option_type=trade.option_type,  # type: ignore[arg-type]
        )
        signed_volume = (
            float(trade.volume) if trade.buy_sell == BuySell.BUY else -float(trade.volume)
        )
        mtm_value = signed_volume * option_value
        # The premium was already paid/received at trade_date; unrealized P&L nets it
        # out of the option's current fair value, the same way a swap's unrealized P&L
        # nets the curve price against the fixed price it was struck at.
        unrealized = mtm_value - signed_volume * float(trade.premium)  # type: ignore[arg-type]
        return ValuationResult(
            trade_id=trade.id,
            book_id=trade.book_id,
            as_of_date=as_of_date,
            curve_id=curve_id,
            mtm_value=mtm_value,
            realized_pnl=0,
            unrealized_pnl=unrealized,
        )

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

        for trade in trades:
            if trade.trade_type != TradeType.OPTION:
                continue
            option_result = self.price_option_trade(
                trade, curve_price_by_month, as_of_date, curve.id
            )
            if option_result is None:
                continue
            results.append(option_result)

        for result in results:
            self._session.add(result)
        await self._session.commit()
        return positions, results
