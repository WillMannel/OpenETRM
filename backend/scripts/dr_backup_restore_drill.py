#!/usr/bin/env python3
"""Disaster-recovery backup/restore drill for task P1-10 -- see ARCHITECTURE.md's
"Production operability, DR, and security review" section and DISASTER_RECOVERY.md
at the repo root for the runbook this proves out.

Seeds a scratch Postgres database with a handful of rows across the tables that
actually need backing up, `pg_dump`s it, drops the database entirely (simulating
total loss), recreates it from the dump via `pg_restore`, and asserts the restored
data matches the pre-loss snapshot exactly -- proving the backup/restore
*mechanism* genuinely round-trips data, not just that `pg_dump`/`pg_restore` exit
0. A DR runbook nobody has ever actually run end to end is a document, not a plan.

Two real-environment gaps this drill can't close here (see DISASTER_RECOVERY.md's
"Known gaps" for the full list):
1. `market_data_points` is a Timescale hypertable in a real deployment; this
   sandbox has no `timescaledb` extension available (same limitation as
   `scripts/benchmark_scale.py` and this repo's migration-validation scripts), so
   this drill builds a plain-table schema via `Base.metadata.create_all()` instead
   of running the real Alembic migrations. `pg_dump`/`pg_restore` of a hypertable
   works the same way as any other table from an operator's perspective (Timescale
   ships pg_dump-compatible hooks for exactly this), but that specific path isn't
   exercised by this drill.
2. This drill uses one Postgres server for both the "source" and the "restored
   from scratch" database -- a real DR drill should also prove restoring onto a
   *different* server, since "the same server's disk survived" is not a real
   disaster scenario. Documented as a real gap, not simulated here.

Usage: DATABASE_URL=postgresql+asyncpg://openetrm:openetrm@localhost:5432/openetrm \\
    python scripts/dr_backup_restore_drill.py
Requires `pg_dump`/`pg_restore`/`psql` on PATH and a Postgres role that can
CREATE/DROP DATABASE. Uses its own scratch database (see DRILL_DB_NAME below), not
the one named in DATABASE_URL -- never points at a database you care about.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET_KEY", "dr-drill-only-not-a-real-secret-" + "x" * 32)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.enums import BuySell, Commodity, Currency, TradeType, VolumeUnit
from app.db.base import Base
from app.modules.trade_capture.models import Book, Counterparty, Trade

DRILL_DB_NAME = "openetrm_dr_drill"
DUMP_PATH = os.path.join(tempfile.gettempdir(), "openetrm_dr_drill.dump")


def _admin_url(sync_url: str) -> str:
    """The `postgres` maintenance DB on the same server -- CREATE/DROP DATABASE
    can't run inside a transaction against the DB being dropped."""
    parsed = urlparse(sync_url)
    return parsed._replace(path="/postgres").geturl()


def _drill_url(sync_url: str) -> str:
    parsed = urlparse(sync_url)
    return parsed._replace(path=f"/{DRILL_DB_NAME}").geturl()


def _recreate_drill_database(sync_url: str) -> None:
    admin_engine = create_engine(_admin_url(sync_url), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DRILL_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{DRILL_DB_NAME}"'))
    admin_engine.dispose()


def _seed(sync_url: str) -> dict[str, object]:
    """Returns a snapshot of what was seeded -- what the post-restore assertions
    compare against."""
    engine = create_engine(_drill_url(sync_url))
    Base.metadata.create_all(engine)  # see module docstring: no timescaledb here
    session_factory = sessionmaker(bind=engine)

    counterparty_id, book_id, trade_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fixed_price = Decimal("3.4275")  # exact Decimal -- proves precision round-trips too
    with session_factory() as session:
        session.add(Counterparty(id=counterparty_id, name="DR Drill Counterparty"))
        session.add(Book(id=book_id, name="DR Drill Book"))
        session.add(
            Trade(
                id=trade_id,
                trade_date=date(2026, 1, 1),
                counterparty_id=counterparty_id,
                book_id=book_id,
                commodity=Commodity.HENRY_HUB,
                trade_type=TradeType.SWAP,
                buy_sell=BuySell.BUY,
                volume=Decimal("12345"),
                volume_unit=VolumeUnit.MMBTU,
                fixed_price=fixed_price,
                price_currency=Currency.USD,
                delivery_start_month=date(2026, 3, 1),
                delivery_end_month=date(2026, 3, 1),
            )
        )
        session.commit()
    engine.dispose()
    return {"trade_id": trade_id, "fixed_price": fixed_price}


def _verify(sync_url: str, snapshot: dict[str, object]) -> None:
    engine = create_engine(_drill_url(sync_url))
    with engine.connect() as conn:
        counts = {
            # Table names come from the fixed tuple below, never user input -- bind
            # parameters can't stand in for identifiers, so f-string interpolation
            # is the only option here.
            table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
            for table in ("counterparties", "books", "trades")
        }
        assert counts == {"counterparties": 1, "books": 1, "trades": 1}, (
            f"row counts didn't survive the restore: {counts}"
        )
        restored_price = conn.execute(
            text("SELECT fixed_price FROM trades WHERE id = :id"),
            {"id": str(snapshot["trade_id"])},
        ).scalar_one()
        assert restored_price == snapshot["fixed_price"], (
            f"Decimal precision didn't survive the restore: "
            f"{restored_price!r} != {snapshot['fixed_price']!r}"
        )
    engine.dispose()


def _run(cmd: list[str], **env_overrides: str) -> None:
    # cmd is always one of this script's own fixed pg_dump/pg_restore argument lists
    # (see main()), never user input.
    env = {**os.environ, **env_overrides}
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"{cmd[0]} failed (exit {result.returncode})")


def main() -> None:
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://openetrm:openetrm@localhost:5432/openetrm"
    )
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    print(f"1. Creating scratch database {DRILL_DB_NAME!r} and seeding it...")
    _recreate_drill_database(sync_url)
    snapshot = _seed(sync_url)

    print("2. Backing up (pg_dump, custom format)...")
    backup_started = time.monotonic()
    _run(["pg_dump", "--format=custom", "-f", DUMP_PATH, _drill_url(sync_url)])
    backup_seconds = time.monotonic() - backup_started
    dump_size_kb = os.path.getsize(DUMP_PATH) / 1024
    print(f"   done in {backup_seconds:.2f}s ({dump_size_kb:.1f} KB)")

    print("3. Simulating total loss (DROP DATABASE)...")
    _recreate_drill_database(sync_url)  # drops and recreates empty -- data is gone

    print("4. Restoring (pg_restore)...")
    restore_started = time.monotonic()
    _run(["pg_restore", "--dbname=" + _drill_url(sync_url), "--no-owner", DUMP_PATH])
    restore_seconds = time.monotonic() - restore_started
    print(f"   done in {restore_seconds:.2f}s")

    print("5. Verifying restored data matches the pre-loss snapshot exactly...")
    _verify(sync_url, snapshot)
    print("   OK -- row counts and Decimal precision both survived the round trip.")

    admin_engine = create_engine(_admin_url(sync_url), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DRILL_DB_NAME}" WITH (FORCE)'))
    admin_engine.dispose()
    os.remove(DUMP_PATH)

    print(
        "\nDrill passed. NOTE: backup_seconds/restore_seconds above are for a handful "
        "of rows on one local machine -- they are not a production RTO estimate; see "
        "DISASTER_RECOVERY.md for how to size that against a real data volume."
    )


if __name__ == "__main__":
    main()
