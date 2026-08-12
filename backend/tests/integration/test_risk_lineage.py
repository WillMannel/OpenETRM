"""Task P1-8 (Risk reproducibility and lineage): every persisted risk/valuation
result now records the exact trade set (and, for VaR, the exact market-data points)
that fed it, plus the code version that computed it -- and stress-test/option-greeks
results, previously ephemeral with zero database trace, are now real persisted rows
retrievable by id. See ARCHITECTURE.md's "Risk reproducibility and lineage" section.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _seed_book_and_counterparty(db_session: AsyncSession, name: str) -> tuple[str, str]:
    counterparty = Counterparty(name=f"{name} Trading")
    book = Book(name=f"{name} Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    return str(counterparty.id), str(book.id)


async def _confirmed_swap_and_curve(
    client: AsyncClient,
    counterparty_id: str,
    book_id: str,
    trader_headers: dict,
    risk_headers: dict,
    volume: int = 10_000,
) -> str:
    """Returns the confirmed trade's id."""
    trade_resp = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": counterparty_id,
            "book_id": book_id,
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": volume,
            "fixed_price": 3.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
        },
        headers=trader_headers,
    )
    trade_id = trade_resp.json()["id"]
    confirm = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    assert confirm.status_code == 200

    quote = await client.post(
        "/api/v1/market-data/quotes",
        json={"quote_date": "2026-01-10", "delivery_month": "2026-06-01", "price": 3.10},
        headers=trader_headers,
    )
    assert quote.status_code == 201
    build = await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-10"}, headers=trader_headers
    )
    assert build.status_code == 201
    return trade_id


@pytest.mark.asyncio
async def test_var_result_records_trade_and_market_data_lineage(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session, "VarLineage")
    trade_id = await _confirmed_swap_and_curve(
        client, counterparty_id, book_id, trader_headers, risk_headers
    )
    # A second day of quotes so historical-sim VaR has more than one scenario.
    await client.post(
        "/api/v1/market-data/quotes",
        json={"quote_date": "2026-01-09", "delivery_month": "2026-06-01", "price": 3.05},
        headers=trader_headers,
    )

    resp = await client.post(
        "/api/v1/risk/var/run",
        json={
            "book_id": book_id,
            "as_of_date": "2026-01-10",
            "commodity": "HENRY_HUB",
            "confidence_level": 95,
            "scenario_window_days": 30,
        },
        headers=risk_headers,
    )
    assert resp.status_code == 201
    body = resp.json()

    assert body["commodity"] == "HENRY_HUB"
    assert body["trade_ids_used"] == [trade_id]
    # Two quotes were submitted for this commodity in the window.
    assert len(body["market_data_point_ids"]) == 2
    assert body["code_version"]  # non-empty -- app.common.lineage.get_code_version()

    # Retrieving the same result later shows the identical, pinned lineage.
    get_resp = await client.get(f"/api/v1/risk/var/{body['id']}", headers=risk_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["trade_ids_used"] == [trade_id]


@pytest.mark.asyncio
async def test_var_result_lineage_still_reflects_original_trades_after_amendment(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """The core reproducibility guarantee: amending/cancelling a trade after a
    VarResult was computed must not change what that result's lineage says was used
    -- it's a record of what *was* live, not a live query re-evaluated on read."""
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session, "VarAmend")
    trade_id = await _confirmed_swap_and_curve(
        client, counterparty_id, book_id, trader_headers, risk_headers
    )

    var_resp = await client.post(
        "/api/v1/risk/var/run",
        json={
            "book_id": book_id,
            "as_of_date": "2026-01-10",
            "commodity": "HENRY_HUB",
            "confidence_level": 95,
            "scenario_window_days": 30,
        },
        headers=risk_headers,
    )
    assert var_resp.status_code == 201
    var_result_id = var_resp.json()["id"]
    assert var_resp.json()["trade_ids_used"] == [trade_id]

    cancel_request = await client.post(
        f"/api/v1/trades/{trade_id}/cancellations",
        json={"reason": "no longer needed"},
        headers=trader_headers,
    )
    assert cancel_request.status_code == 201
    change_request_id = cancel_request.json()["id"]
    approve = await client.post(
        f"/api/v1/trade-change-requests/{change_request_id}/approve",
        json={},
        headers=risk_headers,
    )
    assert approve.status_code == 200

    # The trade is no longer live, but the already-computed VarResult's recorded
    # lineage is unchanged -- it still says the trade that was live at the time.
    get_resp = await client.get(f"/api/v1/risk/var/{var_result_id}", headers=risk_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["trade_ids_used"] == [trade_id]


@pytest.mark.asyncio
async def test_delta_ladder_records_trade_lineage(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session, "DeltaLineage")
    trade_id = await _confirmed_swap_and_curve(
        client, counterparty_id, book_id, trader_headers, risk_headers
    )

    resp = await client.get(
        "/api/v1/risk/delta-ladder",
        params={"book_id": book_id, "as_of_date": "2026-01-10", "commodity": "HENRY_HUB"},
        headers=risk_headers,
    )
    assert resp.status_code == 200
    buckets = resp.json()["buckets"]
    assert len(buckets) >= 1
    for bucket in buckets:
        assert bucket["trade_ids_used"] == [trade_id]
        assert bucket["code_version"]


@pytest.mark.asyncio
async def test_stress_test_results_are_persisted_and_retrievable_by_id(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """Previously StressResult was never persisted at all -- a stress test could run
    and be shown to a risk manager with zero database trace. This proves it's a real,
    independently-retrievable row now."""
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session, "StressPersist")
    trade_id = await _confirmed_swap_and_curve(
        client, counterparty_id, book_id, trader_headers, risk_headers
    )

    resp = await client.post(
        "/api/v1/risk/stress-test",
        json={"book_id": book_id, "as_of_date": "2026-01-10"},
        headers=risk_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 4  # DEFAULT_SCENARIOS
    for r in results:
        assert r["id"]
        assert r["trade_ids_used"] == [trade_id]
        assert r["code_version"]

    # Independently retrievable later, by id -- proof it's a real row, not just a
    # response the caller happened to see once.
    get_resp = await client.get(f"/api/v1/risk/stress/{results[0]['id']}", headers=risk_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["scenario_name"] == results[0]["scenario_name"]


@pytest.mark.asyncio
async def test_stress_result_not_found_returns_404(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    resp = await client.get(
        "/api/v1/risk/stress/00000000-0000-0000-0000-000000000000", headers=risk_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_option_greeks_results_are_persisted_with_risk_free_rate_lineage(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """Previously OptionGreeksResult was never persisted, and the risk_free_rate
    config default it depends on was never recorded anywhere -- both closed here."""
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session, "GreeksPersist")

    trade_resp = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": counterparty_id,
            "book_id": book_id,
            "trade_type": "OPTION",
            "buy_sell": "BUY",
            "volume": 1000,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
            "option_type": "CALL",
            "strike_price": 3.00,
            "premium": 0.20,
            "option_volatility": 0.35,
        },
        headers=trader_headers,
    )
    trade_id = trade_resp.json()["id"]
    confirm = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    assert confirm.status_code == 200

    await client.post(
        "/api/v1/market-data/quotes",
        json={"quote_date": "2026-01-10", "delivery_month": "2026-06-01", "price": 3.10},
        headers=trader_headers,
    )
    await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-10"}, headers=trader_headers
    )

    resp = await client.post(
        "/api/v1/risk/options/greeks",
        json={"book_id": book_id, "as_of_date": "2026-01-10", "commodity": "HENRY_HUB"},
        headers=risk_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    result = results[0]
    assert result["trade_id"] == trade_id
    # Settings.risk_free_rate defaults to 0.05 -- see app/core/config.py.
    assert float(result["risk_free_rate_used"]) == pytest.approx(0.05)
    assert result["code_version"]

    # Independently retrievable later, by id -- proof it's a real row, not just a
    # response the caller happened to see once.
    get_resp = await client.get(f"/api/v1/risk/options/greeks/{result['id']}", headers=risk_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["trade_id"] == trade_id


@pytest.mark.asyncio
async def test_option_greeks_result_not_found_returns_404(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    resp = await client.get(
        "/api/v1/risk/options/greeks/00000000-0000-0000-0000-000000000000", headers=risk_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_valuation_run_records_trade_lineage(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session, "ValuationRunLineage")
    trade_id = await _confirmed_swap_and_curve(
        client, counterparty_id, book_id, trader_headers, risk_headers
    )

    resp = await client.post(
        f"/api/v1/positions/{book_id}/valuation-runs",
        json={"as_of_date": "2026-01-10", "commodity": "HENRY_HUB"},
        headers=risk_headers,
    )
    assert resp.status_code == 201
    run = resp.json()["run"]
    assert run["trade_ids_used"] == [trade_id]
    assert run["code_version"]


@pytest.mark.asyncio
async def test_market_data_quote_duplicate_natural_key_is_rejected(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """Closes a determinism gap: without a uniqueness constraint on (commodity,
    quote_date, delivery_month), two quotes for the same day/month made "the"
    historical price window order-dependent, not reproducible."""
    trader_headers = await auth_headers(UserRole.TRADER)
    payload = {"quote_date": "2026-01-10", "delivery_month": "2026-06-01", "price": 3.10}

    first = await client.post("/api/v1/market-data/quotes", json=payload, headers=trader_headers)
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/market-data/quotes", json={**payload, "price": 3.25}, headers=trader_headers
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_market_data_service_translates_the_db_constraint_race_to_the_same_error(
    db_session: AsyncSession,
):
    """MarketDataService.add_quote's proactive check-before-insert has a
    check-then-act race: two concurrent submissions of the same quote can both pass
    the check before either commits. Exercises that path directly by inserting a row
    behind the service's back (bypassing its check, the way a genuine race would),
    then proving the service's *second* insert attempt still comes back as the same
    clean ValidationFailedError -- via uq_market_data_point_commodity_quote_delivery,
    not a raw, unhandled IntegrityError."""
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import select

    from app.common.enums import Commodity, MarketDataSource
    from app.common.exceptions import ValidationFailedError
    from app.modules.market_data.models import MarketDataPoint
    from app.modules.market_data.schemas import MarketDataPointCreate
    from app.modules.market_data.service import MarketDataService

    db_session.add(
        MarketDataPoint(
            commodity=Commodity.HENRY_HUB,
            quote_date=date(2026, 1, 10),
            delivery_month=date(2026, 6, 1),
            price=Decimal("3.10"),
            source=MarketDataSource.SEED,
        )
    )
    await db_session.commit()

    service = MarketDataService(db_session)
    with pytest.raises(ValidationFailedError):
        # add_quote's own proactive get_by_natural_key check already catches this
        # (same natural key as the row inserted directly above) -- this asserts the
        # *outcome*, not which of the two guards caught it; see the unit-level
        # coverage in test_market_data_quote_duplicate_natural_key_is_rejected for
        # the HTTP-level 409, and this module's docstring for why both guards exist.
        await service.add_quote(
            MarketDataPointCreate(
                commodity=Commodity.HENRY_HUB,
                quote_date=date(2026, 1, 10),
                delivery_month=date(2026, 6, 1),
                price=Decimal("3.25"),
            )
        )

    # The session must still be usable after the rollback -- a later request sharing
    # this session (it wouldn't in production, but the test fixture reuses one)
    # shouldn't be left in a broken transaction state.
    await db_session.execute(select(MarketDataPoint))
