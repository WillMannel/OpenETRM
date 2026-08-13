"""Background jobs for the risk engine (build step 8): VaR and sensitivity runs are
CPU/DB-bound and shouldn't block the request/response cycle."""

import uuid
from datetime import date
from typing import Any

from app.common.enums import Commodity
from app.common.exceptions import NotFoundError
from app.core.db import async_session_factory
from app.modules.auth.repository import UserRepository
from app.modules.risk.service import RiskService


async def _load_actor(session: Any, user_id: str) -> Any:
    """The router that enqueues this job already ran it through require_role, so the
    user existing and being entitled is expected -- re-fetching by id here (rather
    than trusting a role string in the job payload) means RiskService's entitlement
    check still runs against this user's *current* memberships/role at execution
    time, not whatever was true when the job was enqueued."""
    user = await UserRepository(session).get_by_id(uuid.UUID(user_id))
    if user is None:
        raise NotFoundError("User", user_id)
    return user


async def run_var_job(
    ctx: dict[str, Any],
    book_id: str | None,
    as_of_date_iso: str,
    commodity: str,
    confidence_level: int,
    scenario_window_days: int,
    user_id: str,
) -> str:
    async with async_session_factory() as session:
        actor = await _load_actor(session, user_id)
        service = RiskService(session)
        result = await service.run_var(
            uuid.UUID(book_id) if book_id else None,
            date.fromisoformat(as_of_date_iso),
            Commodity(commodity),
            confidence_level,
            scenario_window_days,
            actor=actor,
        )
        return str(result.id)


async def run_sensitivities_job(
    ctx: dict[str, Any], book_id: str, as_of_date_iso: str, commodity: str, user_id: str
) -> str:
    async with async_session_factory() as session:
        actor = await _load_actor(session, user_id)
        service = RiskService(session)
        curve_id, _results = await service.run_delta_ladder(
            uuid.UUID(book_id),
            date.fromisoformat(as_of_date_iso),
            Commodity(commodity),
            actor=actor,
        )
        return str(curve_id)
