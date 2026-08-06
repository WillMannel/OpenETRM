"""Background job wrapping the synchronous curve build (build step 6): the API returns a
job id immediately, the client polls the job status/result via Arq's job API instead of
blocking the request on a potentially-slow curve calibration."""

from datetime import date
from typing import Any

from app.common.enums import Commodity
from app.core.db import async_session_factory
from app.modules.market_data.service import MarketDataService


async def calibrate_curve(ctx: dict[str, Any], commodity: str, as_of_date_iso: str) -> str:
    async with async_session_factory() as session:
        service = MarketDataService(session)
        curve = await service.build_curve(Commodity(commodity), date.fromisoformat(as_of_date_iso))
        return str(curve.id)
