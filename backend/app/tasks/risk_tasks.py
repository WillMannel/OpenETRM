"""Background jobs for the risk engine (build step 8): VaR and sensitivity runs are
CPU/DB-bound and shouldn't block the request/response cycle."""

import uuid
from datetime import date
from typing import Any

from app.common.enums import Commodity
from app.core.db import async_session_factory
from app.modules.risk.service import RiskService


async def run_var_job(
    ctx: dict[str, Any],
    book_id: str | None,
    as_of_date_iso: str,
    commodity: str,
    confidence_level: int,
    scenario_window_days: int,
) -> str:
    async with async_session_factory() as session:
        service = RiskService(session)
        result = await service.run_var(
            uuid.UUID(book_id) if book_id else None,
            date.fromisoformat(as_of_date_iso),
            Commodity(commodity),
            confidence_level,
            scenario_window_days,
        )
        return str(result.id)


async def run_sensitivities_job(
    ctx: dict[str, Any], book_id: str, as_of_date_iso: str, commodity: str
) -> str:
    async with async_session_factory() as session:
        service = RiskService(session)
        curve_id, _results = await service.run_delta_ladder(
            uuid.UUID(book_id), date.fromisoformat(as_of_date_iso), Commodity(commodity)
        )
        return str(curve_id)
