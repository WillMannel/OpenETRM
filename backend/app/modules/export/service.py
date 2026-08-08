"""Bulk, tabular extracts of trades/positions/valuation/risk data -- the REST/HTTP
integration path for pipeline tools (Fabric Data Factory's Web/REST connector, or any
HTTP-capable ETL) that either can't or shouldn't be granted direct database access.
For tools that *can* connect directly to Postgres (Fabric, Power BI, Databricks,
Snowflake all have native Postgres connectors), the reporting views
(alembic/versions/..._reporting_views.py) are the lower-latency, always-current
alternative -- see INTEGRATIONS.md for when to use which.

Every method here returns plain dicts (already flattened -- joined names instead of
raw FKs, Decimal/enum columns coerced to JSON-friendly types) ready to hand to
serialization.rows_to_response, not ORM objects.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.risk.models import VarResult
from app.modules.trade_capture.models import Trade
from app.modules.valuation.models import Position, ValuationResult


def _enum_value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def _trade_row(trade: Trade) -> dict[str, Any]:
    return {
        "id": str(trade.id),
        "trade_date": trade.trade_date.isoformat(),
        "counterparty": trade.counterparty.name,
        "book": trade.book.name,
        "commodity": _enum_value(trade.commodity),
        "trade_type": _enum_value(trade.trade_type),
        "buy_sell": _enum_value(trade.buy_sell),
        "volume": float(trade.volume),
        "volume_unit": _enum_value(trade.volume_unit),
        "fixed_price": float(trade.fixed_price) if trade.fixed_price is not None else None,
        "price_currency": _enum_value(trade.price_currency),
        "delivery_start_month": trade.delivery_start_month.isoformat(),
        "delivery_end_month": trade.delivery_end_month.isoformat(),
        "power_block": _enum_value(trade.power_block) if trade.power_block else None,
        "option_type": _enum_value(trade.option_type) if trade.option_type else None,
        "strike_price": float(trade.strike_price) if trade.strike_price is not None else None,
        "certificate_registry": trade.certificate_registry,
        "vintage_year": trade.vintage_year,
        "status": _enum_value(trade.status),
        "version": trade.version,
        "created_at": trade.created_at.isoformat(),
        "updated_at": trade.updated_at.isoformat(),
    }


def _position_row(position: Position) -> dict[str, Any]:
    return {
        "id": str(position.id),
        "book_id": str(position.book_id),
        "commodity": _enum_value(position.commodity),
        "delivery_month": position.delivery_month.isoformat(),
        "net_volume": float(position.net_volume),
        "avg_fixed_price": float(position.avg_fixed_price),
        "as_of_date": position.as_of_date.isoformat(),
    }


def _valuation_result_row(result: ValuationResult) -> dict[str, Any]:
    return {
        "id": str(result.id),
        "trade_id": str(result.trade_id) if result.trade_id else None,
        "book_id": str(result.book_id) if result.book_id else None,
        "as_of_date": result.as_of_date.isoformat(),
        "curve_id": str(result.curve_id),
        "mtm_value": float(result.mtm_value),
        "realized_pnl": float(result.realized_pnl),
        "unrealized_pnl": float(result.unrealized_pnl),
        "currency": _enum_value(result.currency),
        "computed_at": result.computed_at.isoformat(),
    }


def _var_result_row(result: VarResult) -> dict[str, Any]:
    return {
        "id": str(result.id),
        "book_id": str(result.book_id) if result.book_id else None,
        "as_of_date": result.as_of_date.isoformat(),
        "confidence_level": result.confidence_level,
        "horizon_days": result.horizon_days,
        "method": _enum_value(result.method),
        "var_value": float(result.var_value),
        "computed_at": result.computed_at.isoformat(),
    }


class ExportService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def trades(
        self,
        *,
        book_id: uuid.UUID | None = None,
        updated_since: datetime | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt = select(Trade).order_by(Trade.updated_at.desc()).limit(limit).offset(offset)
        if book_id is not None:
            stmt = stmt.where(Trade.book_id == book_id)
        if updated_since is not None:
            stmt = stmt.where(Trade.updated_at >= updated_since)
        result = await self._session.execute(stmt)
        return [_trade_row(t) for t in result.scalars().all()]

    async def positions(
        self,
        *,
        as_of_date: date,
        book_id: uuid.UUID | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        # Positions are recomputed (not updated in place) on each valuation run, so
        # as_of_date -- which snapshot -- is the natural filter, not an updated_since.
        stmt = (
            select(Position)
            .where(Position.as_of_date == as_of_date)
            .order_by(Position.delivery_month)
            .limit(limit)
            .offset(offset)
        )
        if book_id is not None:
            stmt = stmt.where(Position.book_id == book_id)
        result = await self._session.execute(stmt)
        return [_position_row(p) for p in result.scalars().all()]

    async def valuation_results(
        self,
        *,
        book_id: uuid.UUID | None = None,
        updated_since: datetime | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ValuationResult)
            .order_by(ValuationResult.computed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if book_id is not None:
            stmt = stmt.where(ValuationResult.book_id == book_id)
        if updated_since is not None:
            stmt = stmt.where(ValuationResult.computed_at >= updated_since)
        result = await self._session.execute(stmt)
        return [_valuation_result_row(r) for r in result.scalars().all()]

    async def var_results(
        self,
        *,
        book_id: uuid.UUID | None = None,
        updated_since: datetime | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt = select(VarResult).order_by(VarResult.computed_at.desc()).limit(limit).offset(offset)
        if book_id is not None:
            stmt = stmt.where(VarResult.book_id == book_id)
        if updated_since is not None:
            stmt = stmt.where(VarResult.computed_at >= updated_since)
        result = await self._session.execute(stmt)
        return [_var_result_row(r) for r in result.scalars().all()]
