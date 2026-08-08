"""Bulk export endpoints -- the REST/HTTP integration path. Any authenticated role can
read (matches the existing "VIEWER: read everything" convention), including an
API-key-authenticated service account, which is the expected caller for most of these:
a Fabric Data Factory pipeline, a Power BI scheduled refresh, or similar."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.modules.auth.models import User
from app.modules.export.serialization import ExportFormat, rows_to_response
from app.modules.export.service import ExportService

router = APIRouter(prefix="/export", tags=["export"])

_MAX_LIMIT = 10_000


@router.get("/trades")
async def export_trades(
    format: ExportFormat = "csv",
    book_id: uuid.UUID | None = None,
    updated_since: datetime | None = None,
    limit: int = Query(default=1000, le=_MAX_LIMIT),
    offset: int = 0,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Response:
    service = ExportService(session)
    rows = await service.trades(
        book_id=book_id, updated_since=updated_since, limit=limit, offset=offset
    )
    return rows_to_response(rows, format, "trades")


@router.get("/positions")
async def export_positions(
    as_of_date: date,
    format: ExportFormat = "csv",
    book_id: uuid.UUID | None = None,
    limit: int = Query(default=1000, le=_MAX_LIMIT),
    offset: int = 0,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Response:
    service = ExportService(session)
    rows = await service.positions(
        as_of_date=as_of_date, book_id=book_id, limit=limit, offset=offset
    )
    return rows_to_response(rows, format, "positions")


@router.get("/valuation-results")
async def export_valuation_results(
    format: ExportFormat = "csv",
    book_id: uuid.UUID | None = None,
    updated_since: datetime | None = None,
    limit: int = Query(default=1000, le=_MAX_LIMIT),
    offset: int = 0,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Response:
    service = ExportService(session)
    rows = await service.valuation_results(
        book_id=book_id, updated_since=updated_since, limit=limit, offset=offset
    )
    return rows_to_response(rows, format, "valuation_results")


@router.get("/var-results")
async def export_var_results(
    format: ExportFormat = "csv",
    book_id: uuid.UUID | None = None,
    updated_since: datetime | None = None,
    limit: int = Query(default=1000, le=_MAX_LIMIT),
    offset: int = 0,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Response:
    service = ExportService(session)
    rows = await service.var_results(
        book_id=book_id, updated_since=updated_since, limit=limit, offset=offset
    )
    return rows_to_response(rows, format, "var_results")
