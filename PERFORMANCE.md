# Scale and performance benchmarks

Published, reproducible results for task P1-9 ("Scale and performance engineering
with published benchmarks" — see `ARCHITECTURE.md`'s "Scale and performance"
section for the design/index-audit writeup this data backs). Produced by
`backend/scripts/benchmark_scale.py` — run it yourself; your numbers will differ
from these (hardware-dependent), and that's expected. This document exists to be
honest about what was measured, how, and what it does and doesn't prove — not to
assert a production SLA.

## Environment this run used

- 4 vCPU (Intel Xeon @ 2.80GHz), 15 GiB RAM, local Postgres 16 (no TimescaleDB
  extension available in this sandbox — see the caveat below).
- This is a **development sandbox, not representative production hardware**. Use
  these numbers to judge *relative* cost (which operation dominates, whether an
  index fix helped) and methodology, not as an absolute capacity plan for a real
  deployment.
- **Timescale caveat**: `market_data_points` is a real hypertable in production
  (see `alembic/versions/10aaf6d5f899_initial_schema.py`'s `create_hypertable`
  call), but this sandbox's Postgres has no `timescaledb` extension installed (a
  pre-existing environment limitation — every migration this repo has added since
  has hit the same wall; see e.g. `alembic/versions/e5b8f3a291c7`'s validation
  notes). The benchmark script builds schema via `Base.metadata.create_all()`
  directly, which creates `market_data_points` as an ordinary Postgres table, not
  a hypertable. The VaR/query numbers below are still representative of Postgres's
  b-tree index-scan behavior (what's actually being measured), just not of
  Timescale's chunk-exclusion/compression behavior on top of it.

## Methodology: why these scale targets

Chosen to match a real single-desk energy trading operation, not round numbers
(see `ARCHITECTURE.md`'s index-audit writeup for the full reasoning):

- **10 books × (1,500 live + 3,500 superseded) trades ≈ 50,000 total, 30% live.**
  A mid-size book realistically carries 500–3,000 live trades; `Trade` amendments
  never mutate a row in place (see `Trade.version`/`previous_version_id`) — every
  amendment/cancellation leaves the superseded row in place forever, so a desk
  with a couple of years of activity accumulates far more historical rows than
  live ones. 30% live matches that shape.
- **250-day × 20-delivery-month VaR panel.** 250 trading days is the industry-
  standard 1-year historical VaR window; 20 delivery months is a multi-year
  monthly curve's worth of buckets.
- **10,000-simulation Monte Carlo draw** — this repo's existing default
  (`app/modules/risk/var/monte_carlo.py`), not benchmark-specific.

## Results

### `TradeRepository.list_live` (the query behind position-building, VaR, and
pre-trade limit checks)

| Query | Rows returned | Wall-clock time |
|---|---|---|
| Single book, commodity-scoped | 1,500 | 37–50 ms |
| Portfolio-wide (`book_id=None`), commodity-scoped | 15,000 (across 10 books) | **1.2–1.4 s** |
| Same portfolio-wide predicate, `COUNT(*)` only (no row hydration) | 15,000 matched | **6.3 ms** |

The `COUNT(*)` comparison is the important finding here: it isolates the
query-planner/index cost from the ORM-hydration/network cost. The gap (6 ms vs.
1.2–1.4 s) shows the new index (`ix_trades_commodity_status` — see
`ARCHITECTURE.md`) makes the *query itself* fast; what actually dominates
wall-clock time at 15,000 rows is materializing 15,000 full `Trade` ORM objects,
each eager-joining `Trade.counterparty`/`Trade.book` (`lazy="joined"`, so every
row pulls in two more tables' worth of data even though a risk computation only
needs `volume`/`fixed_price`/`buy_sell`/`delivery_start_month`/etc., never the
counterparty's name). **This is the next bottleneck to fix, once (if) a real
portfolio-wide risk run at this scale becomes a common operation** — the
straightforward fix is a leaner projection query for callers (like
`ValuationService`/`RiskService`) that only need trade economics, not the full
`TradeRead` shape `GET /trades` needs. Not fixed here: it's a real, separable
optimization, not part of what P1-9's index audit targeted, and speculatively
restructuring the ORM loading strategy without a concrete caller that needs it
risks solving the wrong problem. Tracked in `FUTURE_WORK.md`.

Confirmed via `EXPLAIN` that the index is actually used (not just present):
```
Index Scan using ix_trades_commodity_status on trades  (cost=0.29..21.19 rows=1 width=816)
  Index Cond: (((commodity)::text = 'HENRY_HUB'::text) AND ((status)::text = ANY ('{NEW,CONFIRMED,PENDING_AMENDMENT,PENDING_CANCELLATION}'::text[])))
```
(One run showed a `Bitmap Heap Scan` instead of a plain `Index Scan` for the same
query — both are the planner correctly choosing an index-based plan; which one it
picks depends on Postgres's cost estimate for the expected row count, not on
whether indexing worked.)

### `ValuationService.build_positions` (pure in-memory Decimal arithmetic, no DB)

| Input | Wall-clock time |
|---|---|
| 1,500 live trades → 20 positions | 12–17 ms |

Confirms the P1-7 Decimal-arithmetic rewrite (exact `Decimal` summation instead of
`float`) didn't introduce a meaningful performance regression at a realistic
single-book trade count — well under the ~100ms a trader would perceive as latency
on a `GET /positions/{book_id}/pnl` call.

### VaR methods (250-day × 20-month panel, all three methods)

| Method | Wall-clock time |
|---|---|
| `historical_var` | 2.1–2.3 ms |
| `parametric_var` | 2.1–2.5 ms |
| `monte_carlo_var` (10,000 simulations) | 9.8–11.4 ms |

All three are comfortably sub-50ms at this panel size — the quant computation
itself is not the bottleneck at any realistic scale this repo's pilot commodity
scope reaches. This validates the existing sync/async split documented in
`ARCHITECTURE.md`: `/risk/var/run`'s synchronous path blocking the event loop for
~10ms is a non-issue; the worker-backed `/risk/var/run-async` variant exists for
operational flexibility (not tying up a request/response cycle during a batch EOD
run), not because the sync path is actually slow.

## Reproducing this

```
cd backend
sudo -u postgres createdb -O openetrm openetrm_benchmark   # scratch DB -- gets dropped/recreated
DATABASE_URL=postgresql+asyncpg://openetrm:openetrm@localhost:5432/openetrm_benchmark \
  .venv/bin/python scripts/benchmark_scale.py
```
The script seeds ~50,000 trades + 5,000 market-data rows (takes ~10s), then times
each operation. It's idempotent to re-run (drops and recreates every table first)
and uses a fixed random seed, so successive runs on the same machine are directly
comparable to each other.

## What this does *not* cover

- **Concurrency/load**: this measures single-request latency, not throughput under
  concurrent load (no connection-pool contention, no simulated multiple traders
  hitting the API simultaneously). `tests/integration/test_limit_concurrency.py`
  (task P0-5) proves *correctness* under real concurrent Postgres connections, but
  doesn't measure throughput. A real load-testing pass (locust/k6, simulated
  concurrent users) is future work — see `FUTURE_WORK.md`.
- **Timescale-specific behavior**: compression, chunk exclusion, and retention
  policies (none configured — see `ARCHITECTURE.md` and `FUTURE_WORK.md`) aren't
  exercised here at all, per the environment caveat above.
- **Frontend rendering performance**: AG Grid's behavior with a 15,000-row trade
  blotter isn't measured here — this is a backend-only benchmark.
