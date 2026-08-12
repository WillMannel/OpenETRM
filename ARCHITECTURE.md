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

Commodities: **Henry Hub natural gas**, **WTI crude oil**, **coal**, and **power**
(single-hub, peak/off-peak block granularity), plus two environmental certificate
products, **RECs** and **emissions allowances**, that are captured/lifecycle-managed
but not yet curve-valued. See "Power & environmental products" below and
`FUTURE_WORK.md` for what a real power desk still needs (multi-hub/basis trading,
FTRs, BTM PPA economics) that this deliberately doesn't attempt yet.

1. **Auth & audit** (`modules/auth`, `modules/audit`) — JWT auth, RBAC
   (VIEWER/TRADER/RISK_MANAGER/ADMIN), and an append-only audit log every trade
   lifecycle transition writes to atomically. See "Auth, RBAC & audit trail" below.
2. **Trade capture & lifecycle** (`modules/trade_capture`) — counterparties, books,
   trades, and a real state machine: capture → confirm → (optionally amend/cancel
   through four-eyes approval). See "Trade lifecycle" below. Trades are SWAP, FORWARD,
   OPTION, REC, or EMISSIONS_ALLOWANCE (see "Options/optionality" and "Power &
   environmental products" below).
3. **Market data & curve building** (`modules/market_data`) — seed monthly quotes,
   bootstrap a piecewise-flat forward curve (`curve_builder/bootstrapper.py`)
4. **Valuation** (`modules/valuation`) — roll *confirmed* trades into net positions per
   commodity/delivery month, mark-to-market against a published curve; price OPTION
   trades individually via Black-76. Computation and persistence are deliberately
   separate: `GET /positions/{book_id}/pnl` computes fresh and returns it without
   writing anything (safe to call any number of times), while
   `POST /positions/{book_id}/valuation-runs` is the one write path, persisting a new
   `ValuationRun` plus its `Position`/`ValuationResult` rows each time it's called.
   Reporting (`v_positions_flat`/`v_valuation_results_flat`, `ExportService`) always
   reads the latest run for a given book/commodity/as-of-date.
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
8. **Book-level entitlements** (`modules/entitlements`) — desks, per-book membership
   grants, and the service-layer enforcement that turns them into real "Chinese
   walls." See "Book-level entitlements" below.

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

The roles above gate *actions*; *visibility* into a specific book is a separate,
orthogonal concern -- see "Book-level entitlements" below. The first admin is
provisioned out-of-band via `backend/scripts/create_admin.py` (chicken-and-egg:
creating a user with an elevated role itself requires an admin caller).

Every trade lifecycle transition (create, confirm, request amendment/cancellation,
approve/reject) writes an `audit_log` row (`app/modules/audit`) in the *same
transaction* as the change itself — see `TradeCaptureService`, which flushes the state
change and the audit entry together before a single commit, so the two can never
disagree. `GET /audit/{entity_type}/{entity_id}` returns the full history.

### Book-level entitlements (desk separation / "Chinese walls")

`app/modules/entitlements` gates *visibility*: whether a given user may see or act on
a specific book at all, orthogonal to the role-based *action* gating above. A book is
unrestricted by default — any authenticated user with the right role may access it,
exactly today's pre-existing behavior — until it's assigned to a `Desk` (`Book.desk_id`
set via `PUT /books/{book_id}/desk`, ADMIN-only). Once assigned, only ADMIN or a user
holding an explicit `BookMembership` grant for that book (`POST/DELETE
/books/{book_id}/members`, also ADMIN-only) may access it. This is a deliberate
opt-in: it lets an operator wall off individual desks without every existing
book/deployment losing access the moment the feature ships.

Enforcement lives in the *service* layer, not routers — `TradeCaptureService`,
`ValuationService`, `RiskService`, `LimitService`, and `ExportService` each call
`EntitlementService.assert_can_access_book` (a single book) or
`.accessible_book_ids` (filtering a whole-portfolio listing/export to what the caller
can see) before touching book-scoped data, the same way volume-limit enforcement lives
in `TradeCaptureService` rather than being duplicated per route. A denied check raises
`ForbiddenError`, mapped to a 403 at the router layer (distinct from `require_role`'s
403 for the wrong role, and from a 404 for a book that doesn't exist at all). A
portfolio-wide risk run (`book_id=None`, across every book) is ADMIN-only outright,
since there's no single book to check and silently narrowing it to "just the caller's
accessible books" would be a different number under the same "portfolio-wide" label.

The direct-Postgres reporting role (`INTEGRATIONS.md`) does **not** enforce these
walls — it's a single shared, enterprise-wide read role that doesn't authenticate as
an individual user. See `FUTURE_WORK.md` §9 for what real BI-side row-level security
would take.

### Fail-fast secret handling

`Settings.environment` (`app/core/config.py`) defaults to `"production"` — secure by
default, on the theory that the common failure mode is an operator who never set
`ENVIRONMENT` at all, not one who set it wrong. `get_settings()` calls
`_validate_secrets()` after constructing `Settings`: if `JWT_SECRET_KEY` is missing,
equal to the well-known default shipped in this public repo
(`dev-only-insecure-secret-change-me`), or shorter than 32 characters, the process
**refuses to boot** (`RuntimeError`) whenever `ENVIRONMENT=production`. Anywhere else
(`development`/`test`/`staging`) it only logs a warning, so local dev and CI don't need
a real secret to run. `docker-compose.yml` sets `ENVIRONMENT=development` for local
Docker use; `tests/conftest.py` sets `ENVIRONMENT=test` plus a fixed non-secret test
key before any `app.*` module is imported (`get_settings()` is `@lru_cache`'d
process-wide, so whichever env vars are set the *first* time it's called are what
stick for the rest of the process — see that file's comment for the full mechanics).
A real deployment sets `JWT_SECRET_KEY` via `openssl rand -hex 32`, leaves
`ENVIRONMENT` unset (or explicitly `production`), and the app fails loudly at startup
rather than serving forgeable sessions silently. See `tests/unit/core/test_config.py`
for the boundary cases (`_validate_secrets` is a standalone function, tested directly
against constructed `Settings` instances, not through the process-wide cache).

### Enterprise SSO, token refresh & revocation

Three additions to `app/modules/auth` on top of the password-login JWT flow above,
all under task P0-6:

- **Token revocation** — access tokens are stateless HS256 JWTs (no server-side
  session row), which is what lets `get_current_user` validate one without a DB round
  trip on every request. The tradeoff: there's no row to delete on logout. Every
  issued token now carries a unique `jti` claim (`security.issue_access_token`);
  `POST /auth/logout` adds it to a Redis denylist (`app/modules/auth/revocation.py`)
  with a TTL equal to the token's own remaining lifetime, so the denylist entry and
  the token expire at the same moment and never grows unbounded.
  `get_current_user` checks the denylist on every local-JWT request. The default
  SQLite-backed test suite stays Redis-free via a `_FakeRedis` dependency override in
  `tests/conftest.py` (same pattern already used for the Arq pool).
- **Refresh tokens** — `POST /auth/login` now returns an access token *and* a
  refresh token (`RefreshToken`, DB-stored, hashed like an API key). `POST
  /auth/refresh` exchanges a valid, unexpired, unrevoked refresh token for a new
  access+refresh pair, revoking the presented one in the same transaction
  (single-use/rotating, via `RefreshToken.replaced_by_id`). Reusing an
  already-rotated token is treated as a possible compromise, not a normal expiry: it
  revokes the *entire* chain descended from the reused token (see
  `AuthService._revoke_chain_from`'s docstring), forcing a real re-login rather than
  either silently accepting the replay or only blocking the one request.
- **OIDC/Entra ID federation** (`app/modules/auth/oidc.py`) — an *additional* auth
  path, off by default. Setting `OIDC_ISSUER` (+ `OIDC_AUDIENCE`) turns it on;
  `get_current_user` tries an `X-API-Key`, then a local JWT, then — only if OIDC is
  configured and the bearer token isn't one of ours — validates it as an
  externally-issued RS256 token against the provider's published JWKS
  (`jwt.PyJWKClient`, cached per JWKS URL; `OIDC_JWKS_URL` defaults to Entra ID's
  discovery convention if unset). A deployment that never sets `OIDC_ISSUER` is
  completely unaffected. First login auto-provisions a local `VIEWER` user keyed on
  the OIDC `sub` claim (`User.oidc_subject`, unique/nullable) — the one claim every
  OIDC provider guarantees is stable per user, unlike email. OIDC login is an
  *authentication* mechanism only; it never hands out more than the least-privileged
  default role — an admin promotes the account afterward via the existing
  `POST /auth/users`-adjacent path, same as any other user.

Moving `JWT_SECRET_KEY` (and OIDC client secrets, for providers that need one) to a
managed secrets store (Key Vault/Secrets Manager) is deliberately **not** implemented
— see `FUTURE_WORK.md`.

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

### Decimal money and unit-safe quantities

Every persisted money or quantity column (`Trade.volume`/`fixed_price`/`strike_price`
/`premium`, `Position.net_volume`/`avg_fixed_price`, `ValuationResult.mtm_value`
/`realized_pnl`/`unrealized_pnl`, `VarResult.var_value`, `SensitivityResult
.delta_value`, `BookLimit.threshold`, `LimitBreach.threshold`/`observed_value`,
`MarketDataPoint.price`, `CurvePoint.price`) is `Numeric(p, s)` at the DB level, and
always has been — SQLAlchemy returns a real `decimal.Decimal` for those columns on
Postgres *and* SQLite. What wasn't true until this pass: the Python-side type
annotations (`Mapped[float]`) and the service-layer arithmetic on those values lied
about that, casting to `float` at dozens of call sites the moment a value came off
the ORM. That meant every sum/weighted-average over more than a handful of trades —
`ValuationService.build_positions`'s net-volume and volume-weighted-average-price
rollup chief among them, since it feeds MTM, VaR, the delta ladder, stress tests, and
pre-trade volume-limit enforcement simultaneously — accumulated ordinary IEEE-754
binary-float rounding error. `app.common.money` is the fix:

- `Mapped[Decimal]` (not `float`) on every column above, matching what SQLAlchemy
  already returns at runtime. `option_volatility`, `SensitivityResult.bump_size`, and
  `StressResult.pnl_impact` deliberately stay `float` — they're quant model
  *inputs*/computed outputs with no persisted, summed-across-trades exactness
  requirement, not exact trade economics.
- `build_positions`, `attribute_pnl` (P&L attribution), and the VOLUME/VAR limit
  threshold comparisons now do their summation/comparison in `Decimal` throughout,
  not `float`. A limit threshold comparison in particular is a boundary check —
  comparing a float-cast observed value against a float-cast threshold risks the
  comparison itself flipping right at the edge from ordinary rounding, exactly where
  a limit check most needs to be exact.
- `to_decimal(value)` is the one clean conversion point for a quant module's `float`
  output (Black-76, historical-sim/parametric/Monte Carlo VaR, bump-and-revalue
  sensitivities, the piecewise-flat curve bootstrap) crossing back into exact
  arithmetic at the moment it's persisted or compared against a limit — via
  `str(float)`, not `Decimal(float)` directly, to avoid capturing the binary float's
  true value out to 50-odd digits. Quant math itself stays `float`/numpy throughout;
  there's no Decimal support or benefit there, and the actual defect this fixes was
  never inside a single numerical method, only in code that summed/averaged/compared
  many already-exact values afterward.
- The audit log (`TradeCaptureService._trade_snapshot`, `LimitService._record_breach`)
  stringifies (`str(Decimal)`), not float-casts, money/quantity values before writing
  them — an append-only compliance record needs the exact value, and `json.dumps`
  (the JSON column's default serializer) can't encode `Decimal` directly.
- The API/Pydantic layer uses `MoneyDecimal` (`app.common.money`) instead of bare
  `Decimal` for these fields: `Decimal` on the Python side (exact validation), but a
  `PlainSerializer` renders it as a plain JSON number on the wire, not Pydantic v2's
  own default (a JSON *string*). This was a deliberate scope call: the actual bug was
  repeated arithmetic losing precision, not a single, final, correctly-rounded
  JSON-number render of an already-exact value, so keeping the wire format as
  `number` avoided an unrelated, sprawling frontend contract change (generated
  TypeScript types are unaffected on the response side; request-schema types widen to
  `number | string`, harmlessly, since `Decimal` also accepts a string on input).

Unit-safety (not mixing incompatible volume units, e.g. MMBtu and Dth, into one net
position) predates this pass — see task P0-1 and `build_positions`'s explicit
same-bucket unit check, which raises rather than silently blending — and continues to
hold; this pass only changed *how exactly* the numbers within one unit are summed.

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

### Risk reproducibility and lineage

Every persisted risk/valuation result now records *what produced it*, not just the
number itself — the question this answers is "can we prove, months later, exactly
what data and code computed this figure," which matters the moment a number gets
questioned by an auditor, a regulator, or a trader who thinks yesterday's VaR looks
wrong.

- **`trade_ids_used`** (`ValuationRun`, `VarResult`, `SensitivityResult`,
  `StressResult`) — the exact `Trade.id`s that were *live* at computation time and fed
  the number. `ValuationService.build_positions`/`RiskService._net_volume_by_month`
  read *live* trades at call time, not a frozen snapshot — a trade amended or
  cancelled afterward doesn't change the stored result, but without this field there
  was no way to prove *which* trades produced it, only that some set of then-live
  trades did. Set once at computation time; a later amendment/cancellation never
  retroactively updates it (see `tests/integration/test_risk_lineage.py`'s
  amend-after-compute test).
- **`market_data_point_ids`** (`VarResult`) — the exact `MarketDataPoint.id`s that
  composed the historical price panel. VaR (unlike valuation, which pins a `curve_id`)
  consumes a raw range query over quotes with no snapshot of *which* quotes it
  selected; a backdated quote inserted after a VaR run, into the same historical
  window, would otherwise silently change what a later "re-run" sees, with no way to
  detect it happened.
- **`code_version`** (every persisted risk/valuation result) —
  `app.common.lineage.get_code_version()`: a `GIT_SHA`/`GIT_COMMIT` env var if the
  deploy pipeline sets one, else the installed package version. Nothing recorded which
  code version computed a result before this.
- **`risk_free_rate_used`** (`ValuationResult`, for OPTION rows; `OptionGreeksResult`)
  — option pricing consumes a single global config default (`Settings.risk_free_rate`)
  that was previously never recorded anywhere; if it's ever changed, every result
  computed under the old rate stays provably attributable to it instead of silently
  becoming unreproducible.
- **`StressResult`/`OptionGreeksResult` are now real persisted tables** — both were
  previously ephemeral computations returned directly in the HTTP response with *zero*
  database trace. A stress test or a greeks run could happen and be shown to a risk
  manager with no way to later prove it ever ran. `GET /risk/stress/{id}` and `GET
  /risk/options/greeks/{id}` retrieve them independently, the same pattern
  `GET /risk/var/{id}` already established.
- **`uq_market_data_point_commodity_quote_delivery`** — a uniqueness constraint on
  `MarketDataPoint(commodity, quote_date, delivery_month)`. Every market-data write
  path was already insert-only (no `UPDATE` anywhere touches these rows), but without
  this constraint two quotes for the same day/month were both allowed to exist, and
  which one "the" historical price window/latest-quote lookup picked was
  order-dependent — not reproducible, even though nothing was ever edited.
  `MarketDataService.add_quote` checks proactively (a clean 409, not a raw
  `IntegrityError`) and the DB constraint is the backstop against the
  check-then-act race between two concurrent submissions of the same quote.

What this deliberately does **not** attempt (see `FUTURE_WORK.md`): an "as-of"
query service that reconstructs a book's exact state at an arbitrary past timestamp
from the audit log (the raw before/after data is there and exact —
`app.modules.audit` — but there's no query that walks every trade's version chain and
picks the state as of `T`); and a market-data correction/revision flow (today a wrong
quote can only be prevented from being *duplicated*, not corrected — there's no
"supersede this point" workflow).

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

`common.enums.LINEAR_TRADE_TYPES` (`{SWAP, FORWARD}`) is the single source of truth
for which trade types participate in the net-volume rollup at all — `ValuationService.
build_positions` and `RiskService`'s P&L-attribution snapshot both filter through it,
so OPTION and the two certificate trade types below stay excluded consistently rather
than each call site hardcoding its own check.

### Power & environmental products

`Commodity` now covers `POWER` and `COAL` alongside `HENRY_HUB`/`WTI` — both inherited
the existing monthly curve/valuation/risk machinery for free (no commodity-specific
code exists anywhere; adding a `Commodity` value really is just an enum addition, the
same way `WTI` proved it out originally).

Power carries one more field genuinely specific to it: `Trade.power_block`
(`ON_PEAK`/`OFF_PEAK`/`FLAT`) — the defining characteristic of an OTC power product,
required whenever `commodity=POWER` for a SWAP/FORWARD/OPTION. v1 values every block
against the *same* monthly curve price (a documented simplification — a real desk
needs separate peak and off-peak curves; see `FUTURE_WORK.md`).

`TradeType.REC` and `TradeType.EMISSIONS_ALLOWANCE` model renewable energy
certificates and emissions allowances: vintage- and registry-tracked
(`certificate_registry` — free text, e.g. `WREGIS`, `NEPOOL-GIS`, `RGGI` — rather than
an enum, since which registries matter is deployment-specific) certificate trades
priced per-unit (`fixed_price` = $/certificate or $/allowance) instead of against a
delivery-month curve. They go through the exact same capture → confirm → four-eyes
amend/cancel → audit lifecycle as every other trade type, including pre-trade VOLUME
limit checks, but are excluded from `LINEAR_TRADE_TYPES` — v1 has no natural
reference-price time series for a certificate the way it has a forward curve for gas,
so it doesn't mark them at all rather than fabricate a number. `delivery_start_month`/
`delivery_end_month` double as the certificate's vintage (generation/issuance) period
for these two trade types.

Multi-hub power trading, basis swaps, peak/off-peak-differentiated curves, financial
transmission rights, and behind-the-meter PPA revenue economics are real remaining
gaps for a power desk — sketched with concrete architecture in `FUTURE_WORK.md` rather
than built, since getting FTR settlement math or a basis model wrong is worse than not
having it.

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

**Concurrency**: VOLUME enforcement is check-then-act (read live trades, compute a
prospective volume, compare to the threshold), which is a real race under two
concurrent confirms in the same book+commodity — each can read the same pre-confirm
state, each individually pass its check, yet their *combined* effect (once both are
CONFIRMED) breaches the limit. `LimitService.lock_volume_limit` takes a Postgres row
lock (`SELECT ... FOR UPDATE`) on the book's `BookLimit` row *before*
`TradeCaptureService` re-reads live trades, so a second concurrent confirm is forced to
wait for the first's transaction to finish and then recompute against its now-visible
change, rather than racing it. This relies on Postgres's default READ COMMITTED
isolation plus that lock's blocking behavior, not a higher isolation level — see
`LimitService.lock_volume_limit`'s docstring for why that's the deliberate choice, not
an oversight. SQLite (the default test suite's backend) can't demonstrate this race at
all (one connection, no real concurrency), so the regression test
(`test_limit_concurrency.py`) runs only in the `backend-integration-postgres` CI job,
against real concurrent Postgres connections.

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

### Integrations

Two read-only paths for getting data into an external BI/pipeline platform (Fabric,
Power BI, Databricks, Snowflake) — full detail, including per-platform connection
steps, in `INTEGRATIONS.md`:

- **Direct Postgres connector**: flattened `v_*_flat` reporting views
  (`alembic/versions/..._reporting_views.py`) plus a least-privilege read-only role
  (`scripts/create_reporting_role.py`, granting `SELECT` on the views only — never the
  base tables, which would expose `users.hashed_password`/`api_keys.hashed_key`).
- **REST export** (`app/modules/export`): `GET /export/{trades,positions,
  valuation-results,var-results}`, each supporting `format=csv|json|parquet` and (all
  but positions, which key off `as_of_date` instead) `updated_since` for incremental
  pulls. Parquet specifically because that's the format Fabric's OneLake speaks.

Both are authenticated the same way as everything else, including **API keys**
(`app/modules/auth`: `ApiKey`, SHA-256-hashed since it's a high-entropy random token
rather than a human password — see `ApiKey`'s docstring) for service accounts that
shouldn't need an interactive login flow: `get_current_user` accepts either a JWT
bearer token or an `X-API-Key` header, resolving an API key to its associated
service-account `User` so every existing RBAC rule applies unchanged. Admin-only
`POST /auth/users/{id}/api-keys` mints one; the raw key is returned exactly once.

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

Stress testing, P&L attribution, and option greeks have **no async variant** today
(`app/tasks/worker.py` only registers `calibrate_curve`/`run_var_job`/
`run_sensitivities_job`) — both endpoints run the same class of quant math (Black-76,
bump-and-revalue) VaR does, per-scenario/per-trade, directly on the request-handling
event loop. Not an issue at v1's scale (see `PERFORMANCE.md` — all three VaR methods
finish in single-digit milliseconds at a realistic panel size), but the next
candidates for a worker-backed variant if book/scenario sizes grow. Tracked in
`FUTURE_WORK.md`.

### Scale and performance

Task P1-9's index/N+1 audit and its results are published in `PERFORMANCE.md`
(reproducible via `backend/scripts/benchmark_scale.py`) — read that for methodology
and numbers. Summary of what changed:

- **Indexes**: `TradeRepository.list_live` (the query behind position-building, VaR,
  and pre-trade limit checks) has two real call shapes — a single book scoped to a
  commodity, or a portfolio-wide risk run scoped to a commodity (every caller always
  passes a specific commodity; `book_id`/`commodity` are never both unset
  simultaneously in practice). The old book_id-only index only partially served the
  first shape and not at all the second — a portfolio-wide (`book_id=None`) scan was
  a full sequential scan of the entire `trades` table, including every historical
  `AMENDED`/`CANCELLED` row an amendment ever created (amendments never mutate a row
  in place — see `Trade.version`/`previous_version_id` — so superseded rows
  accumulate forever). Added `ix_trades_book_id_commodity_status` and
  `ix_trades_commodity_status` to cover both shapes; also added a `book_id` index to
  `var_results`/`sensitivity_results` (previously none at all — their sibling tables
  `stress_results`/`option_greeks_results` already had one) and a composite
  `(status, book_id)` index to `limit_breaches` (previously status-only, so a
  book-scoped open-breaches lookup still filtered every `OPEN` row globally). All
  purely additive — see `alembic/versions/f9a3c7e18b52_scale_and_performance_indexes.py`.
- **`GET /trades`'s `limit` was unbounded** — a plain `int`, not clamped, so a client
  could pass `?limit=999999999` and force the server to materialize its entire
  entitled trade set into memory. Capped at 1,000 (`Query(le=...)`), matching the
  pattern `app.modules.export`'s bulk endpoints already used.
- **N+1 fix**: `RiskService.compute_option_greeks` looped `session.refresh()` once
  per persisted `OptionGreeksResult` after a single batched commit — N sequential
  round trips for a book with N live option trades, for a result whose fields
  (`id` is a client-side default; everything else is set before commit) were already
  known and never actually needed the refresh. Removed.
- **Confirmed fine as-is**: `ValuationService.build_positions` and all three VaR
  methods are comfortably sub-50ms at realistic scale (`PERFORMANCE.md`) — the
  P1-7 Decimal-arithmetic rewrite didn't introduce a meaningful regression, and the
  quant computation itself was never the bottleneck.
- **Identified, not fixed**: at 15,000 live trades in a single portfolio-wide query,
  ORM object hydration (`Trade.counterparty`/`.book` are `lazy="joined"`, so every
  row pulls in two more tables even when the caller only needs trade economics)
  dominates wall-clock time far more than the query/index itself (see
  `PERFORMANCE.md`'s `COUNT(*)`-vs-hydrated comparison: 6ms vs. 1.2-1.4s for the
  identical predicate). Not fixed here — it's a real, separable optimization (a
  leaner projection query for risk/valuation callers that don't need the full
  `TradeRead` shape) that shouldn't be spec'd out speculatively without a concrete
  caller reaching this scale. Tracked in `FUTURE_WORK.md`.

`market_data_points`' Timescale hypertable (see "Chosen stack") has no compression
or retention policy configured — a bare hypertable with Timescale's default 7-day
chunking. Fine at v1's single-pilot-commodity scale; a multi-commodity, multi-year
desk would want both (`PERFORMANCE.md`'s environment notes explain why this repo's
own sandbox can't exercise Timescale-specific behavior directly). Tracked in
`FUTURE_WORK.md`, deliberately not implemented blind in a migration with no way to
validate it end-to-end here.

### Production operability, DR, and security review

Task P1-10, the last item on the enterprise-hardening backlog. Four pieces:

**CORS + baseline security headers.** `CORSMiddleware` now enforces an explicit
`Settings.cors_allowed_origins` allow-list (never `*` with credentials — `*` and
`allow_credentials=True` together is a real hole, browsers reject the combination
for a reason). A new `SecurityHeadersMiddleware`
(`app/core/middleware.py`) adds `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` to
every response, and `Strict-Transport-Security` conditionally when the request
actually arrived over HTTPS (asserting it unconditionally would be a lie in local
dev/docker-compose, which is plain HTTP).

**Login brute-force protection.** `app/modules/auth/rate_limit.py`: a Redis fixed-
window counter keyed on `(client_ip, username)`, throttling `POST /auth/login`
after `Settings.login_rate_limit_max_attempts` (default 5) failures within
`login_rate_limit_window_seconds` (default 300s), returning 429 + `Retry-After`.
Keyed on the *pair*, not either alone — a distributed attacker guessing many
usernames from one IP or the same username from many IPs gets throttled on
whichever dimension is actually being hammered, without one popular shared
username (a service account) locking out unrelated traffic, or one busy legitimate
IP (many users behind the same NAT/VPN) locking out everyone behind it. Counts
*failures* only and clears on success (`clear_login_attempts`) — a burst of a
legitimate user's successful logins across several tabs is never throttled, and
mistyping a password twice doesn't stay held against you once you get it right.
`request.client.host` is the direct TCP peer, not `X-Forwarded-For` — see the
router's docstring for what a reverse-proxy deployment needs to add
(`ProxyHeadersMiddleware` or equivalent) for this to reflect real client IPs
instead of the proxy's.

**Dependency and static-analysis scanning.** `ruff`'s `S` (flake8-bandit) rule
category is now enabled (`backend/pyproject.toml`) — it found three real
false-positive "hardcoded password" flags (a named sentinel constant, an OAuth2
`token_type` literal, a token-format prefix — all suppressed with a `noqa` stating
why) and zero real findings otherwise. CI gained a `dependency-audit` job:
`pip-audit --local` against the backend's installed dependency tree (catching a
real stale-`setuptools` CVE locally, fixed by upgrading `pip`/`setuptools` first
in the job rather than trusting whatever the runner image happens to bundle), and
`npm audit --omit=dev --audit-level=high` against the frontend's *production*
dependencies specifically (the `vite`/`vitest`/`esbuild` dev-tooling chain carries
its own advisories that don't affect what actually ships — see `FUTURE_WORK.md`
for why that's tracked separately rather than blocking on it). Also bumped
`react-router-dom` 6→7 to close a real open-redirect/XSS advisory in the shipped
bundle — the app's usage (`BrowserRouter`, `Routes`/`Route`, `Navigate`, `Outlet`,
`NavLink`, `useLocation`, `useNavigate`) is exactly the declarative-mode API that's
unchanged between v6 and v7, confirmed by the full frontend suite (tsc/eslint/
vitest/build) staying green after the bump.

**Container hardening and disaster recovery.** Both Dockerfiles are now
multi-stage, run as a non-root user, and carry a `HEALTHCHECK`
(`backend/Dockerfile`, `frontend/Dockerfile`). `frontend/Dockerfile` in particular
was a real gap: it ran the Vite *dev server* as the "production" image. It's now a
proper build (`vite build`) served by `nginxinc/nginx-unprivileged` as static
assets, with the old dev-server image preserved as `Dockerfile.dev` for
docker-compose's local-dev stack specifically (hot reload, runtime
`VITE_API_BASE_URL` — see that file's header comment for why the two can't be the
same image). `DISASTER_RECOVERY.md` is a new backup/restore runbook with RTO/RPO
targets and, critically, an actually-executed drill
(`backend/scripts/dr_backup_restore_drill.py`): seed real data (including an exact
`Decimal` trade price, to prove numeric precision survives) → `pg_dump` → drop the
database entirely → `pg_restore` → assert the restored data matches byte-for-byte.
It also documents *why* Redis needs no backup at all — everything in it is either
short-TTL or ephemeral operational state, never a system of record.

None of this is a substitute for an actual third-party security review before this
platform handles real trading data — see `FUTURE_WORK.md`'s item 13 for exactly
what's still open (production-scale RTO, cross-server restore, WAL-archiving/PITR
infrastructure, container image CVE scanning, the dev-tooling Vite major-version
bump) and why each was deferred rather than rushed.

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
- `quant-golden-coverage`: fails the build if a quant module (option pricing, VaR,
  sensitivities, stress testing, P&L attribution, curve bootstrapping) doesn't carry
  numeric-result assertions derived independently of the implementation, not just
  status-code/shape checks. See `backend/tests/golden/README.md` and
  `backend/scripts/check_quant_golden_coverage.py`.
- `frontend-lint-and-test`: as named.
- `docker-build`: builds `backend/Dockerfile` and both frontend images
  (`frontend/Dockerfile`, the production nginx build, and `Dockerfile.dev`, the
  docker-compose dev-server image) — a broken Dockerfile fails here, not on first
  real deploy.
- `dependency-audit`: `pip-audit` (backend) + `npm audit --omit=dev` (frontend
  production dependencies) — see "Production operability, DR, and security
  review" above.

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
    entitlements/  desks, book memberships, "Chinese wall" enforcement
    export/        bulk CSV/JSON/Parquet extracts for BI/pipeline tools
  tasks/           Arq worker + background jobs (curve calibration, VaR runs)
backend/scripts/   create_admin.py -- bootstrap the first ADMIN user
                   create_reporting_role.py -- bootstrap a read-only BI/pipeline role
backend/tests/     unit tests (pure quant/auth logic) + integration tests (API + in-memory DB)
frontend/src/
  api/             generated OpenAPI types + typed fetch client
  hooks/           React Query hooks per module
  pages/           TradeBlotter, CurveViewer, RiskDashboard, Limits, ApiKeys, Login
```
