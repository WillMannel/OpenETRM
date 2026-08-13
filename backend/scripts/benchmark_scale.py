#!/usr/bin/env python3
"""Scale/performance benchmark harness for task P1-9 -- see ARCHITECTURE.md's
"Scale and performance" section and PERFORMANCE.md at the repo root for the
published, reproducible results this script produced.

Seeds a scratch Postgres database with data at the volumes a real single-desk
energy trading operation actually reaches (see this script's SCALE constants and
PERFORMANCE.md's methodology for how those were chosen -- not arbitrary round
numbers), then times the specific hot-path operations task P1-9's index/N+1 audit
identified: TradeRepository.list_live (book-scoped and portfolio-wide), and the
three VaR methods' compute time at a realistic historical-window panel size.

This is a *development tool*, not a CI gate or a load-testing framework (no
concurrency simulation, no percentile distributions across many runs) -- it exists
to produce honest, reproducible numbers on whatever machine it's run on, not to
assert a pass/fail SLA. Run it yourself and your numbers will differ from
PERFORMANCE.md's; that's expected and stated there.

Usage: DATABASE_URL=postgresql+asyncpg://... python scripts/benchmark_scale.py
Requires a real, empty-or-scratch Postgres -- this DROPS AND RECREATES every table
in the target database. Never point this at a database you care about.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET_KEY", "benchmark-only-not-a-real-secret-" + "x" * 32)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.common.enums import (
    BuySell,
    Commodity,
    Currency,
    MarketDataSource,
    TradeStatus,
    TradeType,
    VolumeUnit,
)
from app.db.base import Base
from app.modules.market_data.models import MarketDataPoint
from app.modules.risk.var.historical_sim import VarInput, historical_var
from app.modules.risk.var.monte_carlo import monte_carlo_var
from app.modules.risk.var.parametric import parametric_var
from app.modules.trade_capture.models import Book, Counterparty, Trade
from app.modules.trade_capture.repository import TradeRepository
from app.modules.valuation.service import ValuationService

# --- Scale targets -----------------------------------------------------------
# Chosen from a single-desk energy trading operation's realistic shape (see
# PERFORMANCE.md's methodology section for the reasoning), not round numbers:
BOOK_COUNT = 10
LIVE_TRADES_PER_BOOK = 1_500  # mid-size book: ~500-3,000 live trades at once
SUPERSEDED_TRADES_PER_BOOK = 3_500  # amendment/cancellation history never deleted
# -> ~50,000 total trades across the desk, ~30% live, matching the survey's
#    "well under half live after a couple of years" observation.
VAR_WINDOW_DAYS = 250  # industry-standard 1-year historical VaR window
VAR_DELIVERY_MONTHS = 20  # a multi-year monthly curve's worth of buckets

DELIVERY_START = date(2026, 6, 1)


@contextmanager
def _timed(label: str):
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    print(f"  {label}: {elapsed * 1000:.1f} ms")


def _random_delivery_month() -> date:
    month_offset = random.randint(0, VAR_DELIVERY_MONTHS - 1)
    year = DELIVERY_START.year + (DELIVERY_START.month - 1 + month_offset) // 12
    month = (DELIVERY_START.month - 1 + month_offset) % 12 + 1
    return date(year, month, 1)


async def seed(session_factory) -> tuple[list[uuid.UUID], uuid.UUID]:
    """Returns (book_ids, first_book_id) after seeding trades + market data."""
    print(
        f"Seeding {BOOK_COUNT} books x "
        f"({LIVE_TRADES_PER_BOOK} live + {SUPERSEDED_TRADES_PER_BOOK} superseded) trades..."
    )
    book_ids: list[uuid.UUID] = []
    async with session_factory() as session:
        counterparty = Counterparty(name="Benchmark Counterparty")
        session.add(counterparty)
        books = [Book(name=f"Benchmark Book {i}") for i in range(BOOK_COUNT)]
        session.add_all(books)
        await session.commit()
        book_ids = [b.id for b in books]
        counterparty_id = counterparty.id

    batch: list[Trade] = []

    def _trade(book_id: uuid.UUID, status: TradeStatus) -> Trade:
        month = _random_delivery_month()
        return Trade(
            trade_date=date(2026, 1, 1),
            counterparty_id=counterparty_id,
            book_id=book_id,
            commodity=Commodity.HENRY_HUB,
            trade_type=TradeType.SWAP,
            buy_sell=random.choice([BuySell.BUY, BuySell.SELL]),
            volume=Decimal(random.randint(100, 10_000)),
            volume_unit=VolumeUnit.MMBTU,
            fixed_price=Decimal(str(round(random.uniform(2.5, 4.5), 2))),
            price_currency=Currency.USD,
            delivery_start_month=month,
            delivery_end_month=month,
            status=status,
        )

    async with session_factory() as session:
        for book_id in book_ids:
            for _ in range(LIVE_TRADES_PER_BOOK):
                batch.append(_trade(book_id, TradeStatus.CONFIRMED))
            for _ in range(SUPERSEDED_TRADES_PER_BOOK):
                batch.append(_trade(book_id, TradeStatus.CANCELLED))
            if len(batch) >= 5000:
                session.add_all(batch)
                await session.commit()
                batch = []
        if batch:
            session.add_all(batch)
            await session.commit()

    print(
        f"Seeding {VAR_WINDOW_DAYS} days x {VAR_DELIVERY_MONTHS} delivery months "
        "of market data quotes..."
    )
    async with session_factory() as session:
        quote_batch: list[MarketDataPoint] = []
        for day_offset in range(VAR_WINDOW_DAYS):
            quote_date = date(2027, 1, 1) - timedelta(days=day_offset)
            for month_offset in range(VAR_DELIVERY_MONTHS):
                year = DELIVERY_START.year + (DELIVERY_START.month - 1 + month_offset) // 12
                month = (DELIVERY_START.month - 1 + month_offset) % 12 + 1
                quote_batch.append(
                    MarketDataPoint(
                        commodity=Commodity.HENRY_HUB,
                        quote_date=quote_date,
                        delivery_month=date(year, month, 1),
                        price=Decimal(str(round(3.0 + random.gauss(0, 0.1), 4))),
                        source=MarketDataSource.SEED,
                    )
                )
            if len(quote_batch) >= 5000:
                session.add_all(quote_batch)
                await session.commit()
                quote_batch = []
        if quote_batch:
            session.add_all(quote_batch)
            await session.commit()

    return book_ids, book_ids[0]


async def benchmark_trade_listing(session_factory, book_ids: list[uuid.UUID]) -> None:
    print("\n--- TradeRepository.list_live ---")
    async with session_factory() as session:
        repo = TradeRepository(session)

        with _timed(f"single book, commodity-scoped ({LIVE_TRADES_PER_BOOK} live rows)"):
            single_book = await repo.list_live(book_ids[0], commodity=Commodity.HENRY_HUB)
        print(f"    -> {len(single_book)} rows returned")

        with _timed(
            f"portfolio-wide (book_id=None), commodity-scoped "
            f"({BOOK_COUNT * LIVE_TRADES_PER_BOOK} live rows across {BOOK_COUNT} books)"
        ):
            portfolio_wide = await repo.list_live(None, commodity=Commodity.HENRY_HUB)
        print(f"    -> {len(portfolio_wide)} rows returned")

    # Isolates the index-scan/query-planning cost from ORM-hydration + network
    # cost: a bare COUNT(*) never materializes a row into a Trade object or joins
    # in counterparty/book (list_live's Trade.counterparty/.book are lazy="joined"
    # -- every row pulls in two more tables), so the gap between this and the timed
    # list_live() call above is roughly "what hydrating N full ORM objects costs."
    async with session_factory() as session:
        with _timed("  (for comparison) same predicate, COUNT(*) only, no row hydration"):
            count_result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM trades WHERE commodity = 'HENRY_HUB' "
                    "AND status = ANY(:statuses)"
                ),
                {"statuses": ["NEW", "CONFIRMED", "PENDING_AMENDMENT", "PENDING_CANCELLATION"]},
            )
        print(f"    -> {count_result.scalar_one()} matching rows")

    async with session_factory() as session:
        print("\n  EXPLAIN for the portfolio-wide query (confirms index usage):")
        result = await session.execute(
            text(
                "EXPLAIN (FORMAT TEXT) SELECT * FROM trades "
                "WHERE commodity = 'HENRY_HUB' AND status = ANY(:statuses)"
            ),
            {"statuses": ["NEW", "CONFIRMED", "PENDING_AMENDMENT", "PENDING_CANCELLATION"]},
        )
        for row in result:
            print(f"    {row[0]}")


async def benchmark_valuation(session_factory, book_id: uuid.UUID) -> None:
    print("\n--- ValuationService.build_positions ---")
    async with session_factory() as session:
        repo = TradeRepository(session)
        trades = await repo.list_live(book_id, commodity=Commodity.HENRY_HUB)
        service = ValuationService.__new__(ValuationService)
        with _timed(f"build_positions over {len(trades)} live trades"):
            positions = service.build_positions(trades, as_of_date=date(2027, 1, 1))
        print(f"    -> {len(positions)} positions produced")


async def benchmark_var(session_factory) -> None:
    import pandas as pd

    print(f"\n--- VaR methods ({VAR_WINDOW_DAYS} days x {VAR_DELIVERY_MONTHS} months panel) ---")
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT quote_date, delivery_month, price FROM market_data_points "
                "WHERE commodity = 'HENRY_HUB' ORDER BY quote_date"
            )
        )
        rows = result.fetchall()

    df = pd.DataFrame(rows, columns=["quote_date", "delivery_month", "price"])
    df["price"] = df["price"].astype(float)
    panel = df.pivot_table(index="quote_date", columns="delivery_month", values="price")
    net_volume = pd.Series({col: random.randint(-5000, 5000) for col in panel.columns}, dtype=float)
    var_input = VarInput(price_history=panel, net_volume_by_month=net_volume)

    with _timed("historical_var"):
        historical_var(var_input, 95)
    with _timed("parametric_var"):
        parametric_var(var_input, 95)
    with _timed("monte_carlo_var (10,000 simulations)"):
        monte_carlo_var(var_input, 95)


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url or "asyncpg" not in database_url:
        print(
            "Set DATABASE_URL to a real, scratch Postgres (postgresql+asyncpg://...) -- "
            "this benchmark needs real query-planner behavior, which SQLite can't provide.",
            file=sys.stderr,
        )
        return 1

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    seed_start = time.perf_counter()
    book_ids, first_book_id = await seed(session_factory)
    print(f"Seed complete in {time.perf_counter() - seed_start:.1f}s\n")

    await benchmark_trade_listing(session_factory, book_ids)
    await benchmark_valuation(session_factory, first_book_id)
    await benchmark_var(session_factory)

    await engine.dispose()
    return 0


if __name__ == "__main__":
    random.seed(1234)  # reproducible seed data across runs
    sys.exit(asyncio.run(main()))
