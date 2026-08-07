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

Pilot commodities: **Henry Hub natural gas** and **WTI crude oil** financial
swaps/forwards (`Commodity.WTI` exists specifically to prove the platform isn't
hardcoded to one commodity, not because oil support is deeply built out).

1. **Auth & audit** (`modules/auth`, `modules/audit`) — JWT auth, RBAC
   (VIEWER/TRADER/RISK_MANAGER/ADMIN), and an append-only audit log every trade
   lifecycle transition writes to atomically. See "Auth, RBAC & audit trail" below.
2. **Trade capture & lifecycle** (`modules/trade_capture`) — counterparties, books,
   trades, and a real state machine: capture → confirm → (optionally amend/cancel
   through four-eyes approval). See "Trade lifecycle" below. Trades are SWAP, FORWARD,
   or OPTION (see "Options/optionality" below).
3. **Market data & curve building** (`modules/market_data`) — seed monthly quotes,
   bootstrap a piecewise-flat forward curve (`curve_builder/bootstrapper.py`)
4. **Valuation** (`modules/valuation`) — roll *confirmed* trades into net positions per
   delivery month, mark-to-market against a published curve; price OPTION trades
   individually via Black-76
5. **Risk** (`modules/risk`) — VaR via historical simulation, parametric
   (variance-covariance), or Monte Carlo; a bucketed delta-ladder; stress testing
   against named shock scenarios; trade-level P&L attribution (price movement vs.
   new trade activity) between two dates; and per-trade option greeks. See "Risk
   methodology" below.
6. **Position & risk limits** (`modules/limits`) — pre-trade volume limits and
   post-hoc VaR limits, both book+commodity-scoped. See "Position & risk limits" below.
7. **Observability** (`app/core/logging.py`, `metrics.py`, `middleware.py`) —
   structured JSON logs with a per-request correlation id, Prometheus metrics, and a
   liveness/readiness split. See "Observability" below.

Explicitly **out of scope** for v1 (see `FUTURE_WORK.md` for a design sketch of each):
full deal settlement/invoicing, regulatory reporting, credit risk/margining, physical
logistics/scheduling, live market data feeds, multi-tenancy.

### Auth, RBAC & audit trail

JWT bearer auth (`app/modules/auth`), four roles enforced via `require_role(...)` at
the route level:

| Role | Can do |
|---|---|
| VIEWER | Read everything. The default for self-registration (`POST /auth/register`). |
| TRADER | + capture trades, seed market data, build curves, request amendments/cancellations |
| RISK_MANAGER | + confirm trades, run risk (VaR/stress/attribution), approve/reject change requests |
| ADMIN | + provision users with any role (`POST /auth/users`) |

There's no per-book ACL yet — any authenticated user can see any book/trade; the roles
above gate *actions*, not *visibility*. The first admin is provisioned out-of-band via
`backend/scripts/create_admin.py` (chicken-and-egg: creating a user with an elevated
role itself requires an admin caller).

Every trade lifecycle transition (create, confirm, request amendment/cancellation,
approve/reject) writes an `audit_log` row (`app/modules/audit`) in the *same
transaction* as the change itself — see `TradeCaptureService`, which flushes the state
change and the audit entry together before a single commit, so the two can never
disagree. `GET /audit/{entity_type}/{entity_id}` returns the full history.

### Trade lifecycle

```
NEW --confirm--> CONFIRMED --request amendment--> PENDING_AMENDMENT --approve--> (old row: AMENDED, new row: CONFIRMED, version+1)
                     |                                    \--reject--> CONFIRMED
                     |
                     +--request cancellation--> PENDING_CANCELLATION --approve--> CANCELLED
                                                       \--reject--> CONFIRMED
```

Only `CONFIRMED`/`PENDING_AMENDMENT`/`PENDING_CANCELLATION` trades count toward
positions/valuation/risk (`common.enums.LIVE_TRADE_STATUSES`) — a draft (`NEW`),
superseded (`AMENDED`), or `CANCELLED` trade must not move a book's P&L. An approved
amendment doesn't mutate the trade row in place; it creates a new `Trade` with
`previous_version_id` pointing at the old one and `version` incremented, so the audit
log and any past valuation/risk runs still refer to the exact terms that were live at
the time. Approval enforces **four-eyes**: the approver may not be the same user who
made the request, checked in `TradeCaptureService._check_pending_and_four_eyes`
regardless of role (an ADMIN can't self-approve either).

### Risk methodology

`POST /risk/var/run` takes a `method`: `HISTORICAL_SIM` (default, unweighted
historical simulation — see the original build's notes), `PARAMETRIC`
(variance-covariance: portfolio variance = wᵀΣw, VaR = z·σ·√horizon — the standard
delta-normal method, `app/modules/risk/var/parametric.py`), or `MONTE_CARLO` (draws
scenarios from a multivariate normal fit to historical price changes and takes the
empirical percentile — `.../monte_carlo.py`; for v1's linear swap/forward payoffs this
should converge close to parametric VaR, which is a useful built-in sanity check).

`POST /risk/stress-test` applies named shocks (absolute or percentage, a default set
of ±10%/±$0.50 or a caller-supplied list) to the curve and reports the P&L impact of
each — a deliberate, not statistically-bounded "what if", unlike VaR
(`.../stress.py`).

`POST /risk/pnl-attribution` decomposes the change in a book's MTM between two dates
into price-movement and new-trade effects, computed trade-by-trade (not off the
position-level average price) so the two effects reconcile to the total by
construction. It does not currently capture trades cancelled/amended away between the
two snapshot dates — see `.../pnl_attribution.py`'s docstring for why (needs a
historical status snapshot per date, which the data model doesn't have yet).

### Options/optionality

`Trade.trade_type` can be `SWAP`, `FORWARD`, or `OPTION`. An OPTION trade carries
`option_type` (CALL/PUT), `strike_price`, `premium` (paid/received at `trade_date`),
and `option_volatility` instead of `fixed_price` (null for OPTION, required for
SWAP/FORWARD — enforced in `TradeCreate`'s validator, not the DB). `delivery_start_month`
doubles as the option's expiry convention.

Pricing (`app/modules/valuation/options.py`) is [Black-76](https://en.wikipedia.org/wiki/Black_model)
— the standard model for options *on a forward/future* rather than spot, which is the
right convention for a commodity option struck against a delivery-month forward.
There's no implied-volatility surface in v1: `option_volatility` is a flat number
captured at trade entry, not derived from market quotes — a documented simplification,
not a real vol surface (a real one is future work). The risk-free rate is a single flat
`Settings.risk_free_rate`, not a yield curve.

Because an option's payoff isn't linear in volume the way a swap/forward's is (two
option trades can carry different strikes/vols), OPTION trades are **excluded** from
`ValuationService.build_positions`'s net-volume rollup and priced individually instead
(`price_option_trade`) — each gets its own per-trade `ValuationResult`
(`trade_id` set, unlike a swap/forward book-level result where it's null). The same
exclusion applies to VaR/delta-ladder/stress/P&L-attribution, which are net-volume-based
and would misrepresent an option's exposure if netted linearly. `POST
/risk/options/greeks` gives per-trade delta/gamma/vega/theta instead.

### Position & risk limits

Two limit types (`modules/limits`), both scoped to a book+commodity, enforced
differently on purpose:

- **VOLUME** — checked pre-trade, at `POST /trades/{id}/confirm`: if confirming would
  push the book's net volume (in any delivery month, across its live SWAP/FORWARD
  trades) past the configured threshold, the confirm is rejected (422) and a
  `LimitBreach` is recorded. Blocking, because a draft trade doing this is still cheap
  to fix (amend or don't confirm).
- **VAR** — checked after `POST /risk/var/run` completes, at a specific confidence
  level: if the run's `var_value` exceeds the threshold, a `LimitBreach` is recorded
  and audited, but the run's result is still returned. Never blocking — a risk report
  must always be able to show an over-limit number, not hide it behind a 4xx.

Both paths write the breach + an `audit_log` entry atomically, the same
flush-then-commit pattern `TradeCaptureService` established. `GET /limits/breaches`
lists open breaches; `POST /limits/breaches/{id}/acknowledge` closes one out (with an
optional note) once a risk manager has reviewed it. `POST /limits` upserts — creating a
second limit of the same (book, commodity, limit_type) updates the existing row's
threshold rather than stacking duplicates.

### Observability

- **Structured logs** (`app/core/logging.py`): every log line is one JSON object
  (timestamp, level, logger, message, plus `request_id` when inside a request) instead
  of the plain-text default — directly parseable by a log aggregator.
- **Request correlation** (`app/core/middleware.py`): `RequestContextMiddleware`
  generates (or propagates, via an inbound `X-Request-ID` header) a per-request id,
  binds it to a `contextvars.ContextVar` so every log call during that request picks it
  up without threading a request object through every function signature, and echoes
  it back as a response header.
- **Metrics** (`app/core/metrics.py`, exposed at `GET /metrics`): Prometheus
  `http_requests_total{method,path,status_code}` and
  `http_request_duration_seconds{method,path}`, labeled by the matched route
  *template* (e.g. `/api/v1/trades/{trade_id}`) rather than the raw path, so per-id
  cardinality doesn't explode.
- **Liveness vs. readiness**: `GET /health` checks nothing external — it only proves
  the process is up, so a slow dependency doesn't make an orchestrator restart a
  perfectly healthy process. `GET /health/ready` pings Postgres and Redis and returns
  503 (with a `checks` breakdown of which dependency failed) if either is unreachable —
  the check a load balancer/readiness probe should actually use.

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
  core/            settings, DB session, logging, metrics, request middleware, Arq pool
  api/v1/          router aggregation
  modules/
    auth/          users, JWT, RBAC (get_current_user, require_role)
    audit/         generic append-only change log
    trade_capture/ counterparties, books, trades, lifecycle (confirm/amend/cancel)
    market_data/   quotes, curve bootstrap (QuantLib + custom bootstrapper)
    valuation/     positions, mark-to-market, Black-76 option pricing (options.py)
    risk/          VaR (historical/parametric/Monte Carlo), sensitivities, stress
                    testing, P&L attribution, option greeks
    limits/        book+commodity VOLUME/VAR limits and breach tracking
  tasks/           Arq worker + background jobs (curve calibration, VaR runs)
backend/scripts/   create_admin.py -- bootstrap the first ADMIN user
backend/tests/     unit tests (pure quant/auth logic) + integration tests (API + in-memory DB)
frontend/src/
  api/             generated OpenAPI types + typed fetch client
  hooks/           React Query hooks per module
  pages/           TradeBlotter, CurveViewer, RiskDashboard, Limits, Login
```
