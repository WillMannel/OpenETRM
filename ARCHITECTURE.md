# Architecture

This document records the stack decision for OpenETRM and the shape of the v1 vertical
slice. See individual module docstrings for implementation-level detail.

## Why this exists

There is no mature, complete open source ETRM (Energy Trading & Risk Management)
platform today — the incumbents (Openlink Endur, Allegro, RightAngle, ...) are all
proprietary. The closest open source prior art is narrower quant/risk tooling:

- **[QuantLib](https://www.quantlib.org/)** (C++, with Python and other bindings) — the
  standard general-purpose quant pricing/curve framework. Huge ecosystem, not
  commodity-specific.
- **[OpenGamma Strata](https://github.com/OpenGamma/Strata)** (Java, Apache 2.0) —
  production-grade market risk analytics (curve calibration, PV01/sensitivities), but
  rates/FX-oriented.
- **[Open Source Risk Engine (ORE)](https://github.com/OpenSourceRisk/Engine)**
  (C++/QuantLib, BSD, sponsored by Acadia) — the most complete open source risk/XVA
  platform, with real commodity derivative coverage (forwards, swaps, options, APOs),
  but built for bank XVA/exposure simulation rather than trade-capture-first ETRM
  workflow.
- **[cmdty](https://github.com/cmdty)** (`cmdty.curves`, `cmdty.storage` — Python + .NET,
  MIT) — the most directly relevant prior art: purpose-built commodity forward-curve
  construction and storage valuation, exactly the shape of problem ETRM curve-building
  needs.

OpenETRM is filling a real gap rather than competing with an existing open source
leader, so the stack choice optimizes for OSS contributor accessibility + numerical/quant
ecosystem fit + typed correctness for financial domain logic, not for matching an
incumbent's technology.

## Stack comparison

| | TypeScript (Node/NestJS) | Java/Kotlin (Spring) | **Python (FastAPI)** | .NET (C#) |
|---|---|---|---|---|
| Numerics/quant ecosystem | Weak — no numpy-equivalent, would need WASM/native addons | Strong via Strata/QuantLib-JNI, but heavier | **Strongest for OSS: NumPy/pandas/SciPy + QuantLib-Python + `cmdty` prior art directly reusable** | Strong (`cmdty` has .NET bindings too), less common in OSS finance |
| Typed correctness | Good (TS) | Best (JVM static typing) | Good enough w/ Pydantic v2 + mypy | Best |
| OSS contributor pool | Very large | Large but higher barrier to entry | **Very large, and specifically overlaps with the quant/data-science crowd this project needs** | Smaller OSS mindshare |
| Precedent in real ETRM/quant tooling | Little | Some (Strata) | **Most direct (`cmdty`, QuantLib-Python)** | Some (`cmdty`) |
| Fit for curve building, VaR, sensitivities | Poor without a second runtime | Good | **Best** | Good |

**Decision: Python.** FastAPI backend, React/TypeScript frontend. The hard requirement
for v1 — real curve bootstrapping, historical-simulation VaR, and bucketed
sensitivities — is exactly what Python's ecosystem is built for, and it draws from the
same contributor pool as the one existing open source project doing this well
(`cmdty`). A JS-only stack would need a second runtime for the numerics. The frontend
stays TypeScript since the UI has no numerics need and TS is the strongest choice there;
FastAPI's generated OpenAPI schema produces a typed TS client (`openapi-typescript` +
`openapi-fetch`) so the frontend/backend boundary stays honest despite being polyglot.

## Chosen stack

- **Backend**: Python 3.11+, FastAPI (async), Pydantic v2, SQLAlchemy 2.0 + Alembic
- **DB**: PostgreSQL 16 + TimescaleDB extension — `market_data_points` is a hypertable
  partitioned on `quote_date`; everything else is a plain relational table
- **Quant/risk**: QuantLib-Python for calendar/day-count scaffolding, a custom
  piecewise-flat monthly curve bootstrapper modeled on `cmdty.curves`, NumPy/pandas/SciPy
  for historical-simulation VaR and bump-and-revalue sensitivities
- **Async jobs**: [Arq](https://arq-docs.helpmanual.io/) + Redis — async-native, so job
  functions reuse the same async SQLAlchemy session pattern as the API instead of
  Celery's sync-worker/async-app impedance mismatch. Revisit Celery only if job
  orchestration grows complex multi-step chains.
- **Frontend**: React 18 + TypeScript + Vite, AG Grid Community (trade blotter/grids),
  TanStack Query, Recharts, Tailwind
- **Contract**: FastAPI's OpenAPI schema → `openapi-typescript`-generated TS types,
  consumed through a thin `openapi-fetch` client (`frontend/src/api/client.ts`)
- **Architecture**: a modular monolith — one API process, one worker process — split
  into bounded-context modules (`trade_capture`, `market_data`, `valuation`, `risk`)
  under `backend/app/modules/`. Clean internal seams so pieces can become real services
  later without paying microservice cost now.
- **Dev/deploy**: Docker Compose (postgres/timescale, redis, api, worker, web); GitHub
  Actions CI (lint, backend/frontend tests, docker image builds)

## v1 vertical slice

Pilot commodity: **Henry Hub natural gas** financial swaps/forwards only.

1. **Trade capture** (`modules/trade_capture`) — counterparties, books, and trades
   (buy/sell, volume, fixed price, delivery month range)
2. **Market data & curve building** (`modules/market_data`) — seed monthly quotes,
   bootstrap a piecewise-flat forward curve (`curve_builder/bootstrapper.py`)
3. **Valuation** (`modules/valuation`) — roll trades into net positions per delivery
   month, mark-to-market against a published curve
4. **Risk** (`modules/risk`) — 1-day historical-simulation VaR and a bucketed
   delta-ladder (bump-and-revalue sensitivities per tenor)

Explicitly **out of scope** for v1 (future work, not built): full deal lifecycle
(confirmations/settlement/invoicing), regulatory reporting, multiple asset classes,
options/optionality, live market data feeds, auth/multi-tenancy hardening.

### Async job endpoints

Curve build, VaR, and delta-ladder each have a synchronous endpoint (blocks until done —
fine at v1's size) and an async counterpart that enqueues onto the Arq worker and
returns a job id to poll:

| Sync | Async enqueue | Poll |
|---|---|---|
| `POST /curves/build` | `POST /curves/build-async` | `GET /curves/build-async/{job_id}` |
| `POST /risk/var/run` | `POST /risk/var/run-async` | `GET /risk/var/run-async/{job_id}` |
| `GET /risk/delta-ladder` | `POST /risk/delta-ladder/run-async` | `GET /risk/delta-ladder/run-async/{job_id}` |

`GET .../{job_id}` returns `{job_id, status, result}` where `status` is one of Arq's
`deferred | queued | in_progress | complete | not_found` and `result` is the created
row's id once `complete`. The frontend doesn't use these yet (v1's data volumes are
small enough that the sync path is fine) — they exist so heavier workloads have
somewhere to go without an API shape change. `app/core/jobs.py` has the pool/polling
details.

## CI

- `backend-lint` / `backend-test`: SQLite-backed, no external services, fast.
- `backend-integration-postgres`: the one job that's actually representative of
  production — real Postgres/TimescaleDB + Redis service containers, runs the real
  Alembic migration (not `Base.metadata.create_all`), and runs
  `tests/integration/test_worker_e2e.py` (skipped by default elsewhere) against a real
  Arq worker subprocess to prove the async job path actually works end to end, not just
  that it enqueues.
- `contract-check`: regenerates the frontend's TS types from the backend's live OpenAPI
  schema and diffs against the committed `frontend/src/api/generated/types.ts`, so the
  two can't silently drift apart.
- `frontend-lint-and-test`, `docker-build`: as named.

## Repository layout

```
backend/app/
  core/            settings, DB session, logging
  api/v1/          router aggregation
  modules/
    trade_capture/ counterparties, books, trades
    market_data/   quotes, curve bootstrap (QuantLib + custom bootstrapper)
    valuation/     positions, mark-to-market
    risk/          VaR (historical simulation) + sensitivities (delta ladder)
  tasks/           Arq worker + background jobs (curve calibration, VaR runs)
backend/tests/     unit tests (pure quant logic) + integration tests (API + in-memory DB)
frontend/src/
  api/             generated OpenAPI types + typed fetch client
  hooks/           React Query hooks per module
  pages/           TradeBlotter, CurveViewer, RiskDashboard
```
