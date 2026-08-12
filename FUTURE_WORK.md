# Future Work

This is a design sketch, not an implementation plan to execute blindly. Each area
below is a substantial standalone subsystem at a real ETRM vendor, built by teams with
deep regulatory/ops/power-market domain expertise. Building any of them to real
completeness in a single pass would mean guessing at requirements (regulatory field
formats, CSA/margin mechanics, GL chart-of-accounts conventions, pipeline nomination
protocols, ISO/RTO settlement specifics) that genuinely need a domain expert or a
specific target jurisdiction/counterparty/ISO to get right. What follows is enough to
know where each one would attach to the existing architecture and roughly how big it
is, so a future pass has a real starting point instead of a blank page.

Sections 1-4 were the original four deferred areas. Sections 5-7 were added once the
platform broadened into power (POWER commodity, peak/off-peak blocks) and
environmental certificates (REC, EMISSIONS_ALLOWANCE) -- each of those three is a real
gap specifically for a power-trading desk that this repeats the same honesty about:
sketched, not built, because getting them wrong (bad FTR settlement math, a basis
model that silently mis-prices real risk) is worse than not having them. Section 8 was
added once external-system integration (`INTEGRATIONS.md`: a direct-connect reporting
role and REST export endpoints) landed -- it covers what a *tighter* Fabric/pipeline
integration still needs on top of that.

## 1. Regulatory Reporting

**Scope**: EMIR (EU), Dodd-Frank/CFTC Part 45 (US), REMIT (EU energy-specific), MiFID II
transaction reporting. Each has its own field set, its own reporting counterparty
(trade repository) integration, its own timing (T+1, real-time), and its own UTI/UPI
(Unique Trade/Product Identifier) generation and lifecycle-event reporting rules
(new/modification/cancellation/valuation all need separate report types under most
regimes).

**Where it attaches**: A new `modules/regulatory_reporting` module, subscribing to the
same lifecycle events `modules/audit` already captures (CREATE, CONFIRM,
APPROVE_CHANGE). Each jurisdiction's report format would be its own submodule
(`emir.py`, `dodd_frank.py`, ...) mapping a `Trade` + its audit trail into that regime's
XML/CSV/API payload. Reports would be generated as Arq background jobs (the pattern
`app/tasks/` already establishes) and either written to a file drop or pushed to a
trade repository's API, depending on jurisdiction.

**Sizing**: each regime is realistically its own multi-week effort once the actual
target trade repository/reporting mechanism is known; this isn't something to
speculatively build against no real reporting destination.

## 2. Credit / Counterparty Risk & Margining

**Scope**: per-counterparty credit limits, exposure aggregation (current MTM exposure +
potential future exposure), limit breach alerting, and margining (initial margin +
variation margin under an ISDA CSA — Credit Support Annex — with threshold, minimum
transfer amount, and eligible collateral haircut rules).

**Where it attaches**: A new `modules/credit_risk` module. Exposure aggregation reuses
`ValuationService.mark_to_market` per counterparty rather than per book (today's
`Position`/`ValuationResult` are book-scoped; counterparty-scoped exposure would need a
`counterparty_id` rollup — either a new query path or, cleaner, add `counterparty_id`
onto `Position`/`ValuationResult` now so both rollups are available without a schema
change later). Variation margin calls would run as a scheduled daily job (a new Arq
cron-style job, or a `CronCreate`-driven trigger at the orchestration layer) comparing
today's exposure against yesterday's collateral balance.

**Sizing**: exposure aggregation alone is a moderate lift on the existing valuation
code. CSA-compliant margining (threshold/MTA/haircut mechanics, margin call
workflow with counterparty confirmation) is a much larger, correctness-critical
effort — this is real money moving between counterparties, and needs careful review
against actual CSA terms, not a best-guess implementation.

## 3. Settlement / Invoicing

**Scope**: converting a matured/expired trade's floating-price settlement into
realized cash flow, generating an invoice (or accepting the counterparty's), tracking
payment status, and posting to a general ledger.

**Where it attaches**: A new `modules/settlement` module. The natural trigger is a
trade's `delivery_end_month` passing `as_of_date` — a scheduled job would identify
trades that have "matured" (delivery period ended) and haven't yet been settled, look up
the realized floating index fixing for that period (this needs a new market-data
concept: fixings, distinct from the forward curve quotes `modules/market_data` handles
today), and compute realized P&L = signed_volume * (floating_fixing - fixed_price).
`ValuationResult.realized_pnl` already exists as a field for exactly this (currently
always `0` — see `ValuationService.mark_to_market`'s docstring) and would start being
populated. Invoice generation and GL posting would be their own submodules, since the
correct behavior there depends entirely on the deploying organization's invoicing
format and chart of accounts.

**Sizing**: the settlement calculation itself (given a fixing) is a small, well-scoped
addition. Fixings ingestion, invoice generation/matching, and GL integration are each
their own scoped efforts depending on what index/invoicing/accounting systems a real
deployment needs to integrate with.

## 4. Logistics / Physical Scheduling

**Scope**: nominations (daily/monthly volume requests to a pipeline or terminal),
pipeline/storage capacity management, transportation scheduling, and physical
delivery confirmation -- relevant only for `trade_type` values beyond today's
financially-settled `SWAP`/`FORWARD` (a genuinely physical forward with delivery
obligations, not just a financial settlement).

**Where it attaches**: A new `modules/logistics` module, with its own `Nomination`
entity (trade reference, delivery point, nominated volume, nomination date, status)
and a state machine roughly parallel to `TradeChangeRequest`'s (nominated → confirmed
by counterparty/pipeline → scheduled → delivered). This is architecturally the most
different from what exists today -- it's coordination with an external
counterparty/pipeline's own system (EDI, API, or portal), not a self-contained
calculation like curve building or VaR.

**Sizing**: the largest of the four by a wide margin. Real physical scheduling
systems are entire products on their own (this is what dedicated nomination/scheduling
software does). Worth deferring until there's a specific physical delivery point and
counterparty integration to build against.

## 5. Financial Transmission Rights (FTRs)

**Scope**: FTRs (called CRRs in CAISO, TCCs in NYISO) don't fit `Trade`'s buy/sell +
volume + fixed_price shape at all -- an FTR is unidirectional, defined by a
**point-of-receipt and point-of-delivery node pair**, an MW quantity, and a contract
period (typically monthly/quarterly/annual auction rounds, not continuously-traded OTC
like a swap). It pays the holder the day-ahead LMP congestion difference between the
two nodes for the contract period: `payoff = MW * (DA_LMP[delivery_node] -
DA_LMP[receipt_node])` (a "counter-flow" FTR has the sign flipped). Settlement needs
actual day-ahead LMP data at both nodes for every day in the period, published by the
ISO/RTO after the fact -- this is fundamentally a different data feed from the forward
curve quotes `modules/market_data` ingests today.

**Where it attaches**: A new `modules/ftr` module with its own `FtrPosition` entity
(source node, sink node, MW, contract period, auction/OTC acquisition price) --
deliberately *not* bolted onto `Trade`, since forcing a two-node instrument through a
one-commodity/one-price schema would corrupt every place that reads `Trade` generically
(position netting, VaR, limits). Settlement would be its own scheduled job that pulls
DA LMPs (an ISO-specific data source/format per RTO -- PJM, MISO, ERCOT, CAISO, etc.
all publish differently) and computes realized congestion revenue per position per day.

**Sizing**: capture + a static congestion-revenue calculator (given LMP data already in
hand) is a moderate, well-scoped effort. The real cost is the LMP ingestion pipeline --
one per target ISO, each with its own API/file format and update cadence -- which is
exactly the kind of "needs a specific target integration to build against" problem the
other four sections above already called out.

## 6. Multi-hub power trading, basis swaps, and peak/off-peak-differentiated curves

**Scope**: today `Commodity.POWER` is one undifferentiated value (like `HENRY_HUB` or
`WTI` already are) -- there's no way to express "PJM West Hub" vs. "ERCOT North Hub" as
distinct tradeable/curve-able instruments, and no way to express a **basis swap** (the
price difference between two delivery points, e.g. a specific plant's node vs. its
regional hub -- exactly the kind of position a generation owner uses to hedge basis
risk between where they generate and where the liquid hub prices). `PowerBlock`
(ON_PEAK/OFF_PEAK/FLAT) exists on `Trade` today but all three value against the *same*
monthly curve price -- a real desk needs separate peak and off-peak curves, since
on-peak and off-peak power trade at genuinely different price levels.

**Where it attaches**: the honest fix is promoting **delivery point** to a first-class
dimension, decoupling "what" (`Commodity`) from "where" (a new `delivery_point: str`
field on `Trade`, `MarketDataPoint`, and `ForwardCurve`/`CurvePoint`, alongside
`commodity`). Curves and positions would then key off `(commodity, delivery_point,
delivery_month, power_block)` instead of just `(commodity, delivery_month)`. A basis
swap becomes a trade with both `delivery_point` (long leg) and a new
`basis_reference_point` (short leg), valued as `net_volume * ((curve[delivery_point] -
curve[basis_reference_point]) - fixed_basis)`. Peak/off-peak curves fall out of the
same generalization once `power_block` is part of the curve's key, not just the
trade's.

**Sizing**: this is the single highest-leverage next increment for a power desk --
larger than section 5 or 7, but the most broadly enabling (unlocks real multi-hub
trading, basis hedging, and correct peak/off-peak MTM all at once). It touches
`ValuationService.build_positions`/`mark_to_market`, `MarketDataRepository`,
`RiskService`'s net-volume-by-month logic, and every place `Position` is grouped --
worth doing as its own dedicated pass with real test coverage per touched service,
not a bolt-on to something else.

## 7. Behind-the-meter PPA economics

**Scope**: a behind-the-meter deal -- a generation asset selling directly to a
co-located large load (a data center, an industrial site) rather than through the
wholesale/ISO market -- is economically closer to a long-dated bilateral forward than
to a dispatch-optimization problem: a fixed or index-linked price, a long tenor
(multi-year), and (usually) a specific delivery/settlement point tied to the physical
asset. The complexity a real desk needs on top of a plain forward is **revenue
allocation**: the same physical asset often sells part of its output BTM and sells (or
buys, to cover a shortfall) the rest into the wholesale market, and the two streams
need to reconcile against the asset's actual metered generation.

**Where it attaches**: a new `Asset` entity (capacity, technology, interconnection/
delivery point) that a `Trade` can optionally reference (`asset_id`, nullable --
existing purely-financial trades wouldn't set it), plus a small reconciliation service
comparing an asset's metered output for a period against the sum of its BTM-allocated
and wholesale-allocated trade volumes for that same period, flagging the shortfall/
surplus. This deliberately does **not** mean building DER dispatch/optimization
software (that's a genuinely different product -- VPP/DERMS platforms like AutoGrid,
Stem, Enel X -- not an ETRM's job); it means tracking the commercial/financial side of
a deal that already happened or is already scheduled.

**Sizing**: the `Asset` entity + `Trade.asset_id` + basic capture is a small,
well-scoped addition once section 6's delivery-point generalization exists (a BTM deal
has a delivery point too). The metered-vs-contracted reconciliation needs a real
metering data feed (utility/ISO settlement data, or the asset's own SCADA/metering
system) to be anything more than a stub -- same "needs a specific integration" caveat
as sections 1 and 5.

## 8. Outbound webhooks and a native OneLake write path

**Scope**: `INTEGRATIONS.md` covers two pull-based integration paths today (a
direct-connect read-only Postgres role, and REST export endpoints). Both need an
external system to ask; neither pushes. Two real improvements on top of that:

- **Outbound webhooks**: on a trade lifecycle event (the same set `modules/audit`
  already captures -- CREATE, CONFIRM, APPROVE_CHANGE, ...), POST a payload to one or
  more subscriber-configured URLs. This is what would let Fabric's Eventstream or Data
  Activator react to a trade in near-real-time instead of a pipeline polling
  `/export/trades?updated_since=...` on a schedule.
- **A native OneLake write path**: instead of waiting for a Fabric pipeline to pull
  from `/export/*`, have this service itself write Parquet directly to a OneLake
  ADLS Gen2 endpoint on a schedule (an Arq job, following the pattern
  `app/tasks/` already establishes) -- push instead of pull.

**Where they'd attach**: webhooks need a new `modules/webhooks` module (subscription
CRUD -- URL, event types, an HMAC signing secret for the receiver to verify
authenticity -- plus a delivery worker with retry/backoff, since a subscriber's
endpoint being briefly down shouldn't drop the event) hooking into the same point
`record_audit_event` already does. The OneLake writer would extend
`app.modules.export` with a scheduled job instead of an on-demand endpoint, using
Azure's ADLS Gen2 SDK against OneLake's endpoint and a service principal.

**Sizing**: webhooks are a moderate, well-scoped effort with a clear existing hook
point (audit events) -- the main correctness-sensitive piece is delivery
reliability (retries, dead-lettering, signature verification), not the event
detection itself. The OneLake writer is smaller in code but the one item on this
entire list that's fundamentally untestable without a real Fabric workspace and Azure
AD app registration to authenticate against -- there's no way to responsibly build
and claim it works without that, so it stays a sketch until someone has one to build
against.

## 9. Desk-wide entitlement grants and BI-side row-level security

**Scope**: `app.modules.entitlements` (book-level "Chinese walls") ships two
deliberate simplifications worth widening later:

- **Desk-wide membership grants**: today, entitlement to a walled book is granted
  per-book (`BookMembership`), even though books already belong to a `Desk`. A trader
  who joins a 20-book desk needs 20 grants instead of one "join this desk" grant. A
  `DeskMembership` entity (mirroring `BookMembership` but keyed on `desk_id`) with
  `EntitlementService.assert_can_access_book` checking it as a second path alongside
  `BookMembership` is a small, additive change once there's a real desk with enough
  books that per-book grants become tedious.
- **BI-side row-level security**: `EntitlementService` enforces desk separation in the
  application/API layer, but the direct-Postgres reporting role
  (`scripts/create_reporting_role.py`, see `INTEGRATIONS.md`) is intentionally a single
  shared, enterprise-wide read role -- a Fabric/Power BI connection through it sees
  every book's data in `v_positions_flat`/`v_trades_flat`/etc. regardless of desk walls,
  because it doesn't authenticate as an individual OpenETRM user at all. Real row-level
  BI entitlement would need either (a) a Postgres role per desk with a `USING
  (desk_id = current_setting('app.desk_id'))` row-level-security policy on each base
  table, provisioned and rotated per desk, or (b) a generated view per desk. Both are
  real, buildable extensions of the existing `..._reporting_views.py` migration
  pattern, deferred because provisioning/rotating per-desk Postgres credentials is an
  operational process, not just a schema change, and no desk has asked for BI-level
  separation yet -- see `app.modules.entitlements.service` for where the API-level
  enforcement already lives if/when this is picked up.
- **404 vs. 403 on a walled book an outsider doesn't know about**:
  `EntitlementService.assert_can_access_book` currently returns 403 (not 404) for a
  book that exists but the caller can't see, which technically confirms the book id is
  valid to anyone probing it. A stricter implementation would 404 instead, matching
  how `NotFoundError` is already used elsewhere -- deferred because it complicates the
  common admin/support case of explaining *why* an access attempt failed, and no real
  deployment has asked for it.

## 10. Managed secrets store

**Scope**: `JWT_SECRET_KEY` (and, for OIDC providers that need one, a client secret)
is read from a plain environment variable today (`app/core/config.py`), fail-fast
validated at boot (see `ARCHITECTURE.md`'s "Fail-fast secret handling"), but not
fetched from or rotated through a dedicated secrets manager (Azure Key Vault, AWS
Secrets Manager, HashiCorp Vault, ...). Deferred deliberately rather than half-built:
this repo doesn't target one specific cloud/platform, and a real integration means
pulling in that platform's SDK, wiring up its auth (managed identity / IAM role /
Vault token), and — the part that actually matters — a rotation story (the app must
pick up a rotated secret without a restart, or an operator needs a documented restart
process), none of which is meaningfully testable without a live instance of that
specific service. The natural seam for this already exists:
`Settings.jwt_secret_key`/`oidc_*` are plain fields read once at process start by
`get_settings()` — swapping their source from `os.environ` to a secrets-manager
client is a config-loading change, not a change to anything that uses `get_settings()`
today. Whoever deploys this to a specific cloud is the right place to decide which
platform's secrets manager to integrate.

## 11. As-of state reconstruction and market-data correction

**Scope**: two gaps deliberately left open by task P1-8 ("Risk reproducibility and
lineage" — see `ARCHITECTURE.md`), both real but each a genuinely separate feature
from what that task closed:

- **As-of query service**: `app.modules.audit` already records an exact, append-only
  before/after snapshot of every trade lifecycle transition (`_trade_snapshot`,
  stringified Decimals, not lossy floats), and `Trade.version`/`previous_version_id`
  chains an amendment to the row it superseded. What doesn't exist is a service that
  *uses* that data to answer "what was book X's exact trade population as of
  timestamp T" — walking every trade's version chain, picking the audit entry with
  the latest `occurred_at &lt;= T`, and reconstructing the implied trade set. `trade_ids
  _used` (P1-8) proves what a *specific already-computed result* used; this would be
  the complementary capability of reconstructing that same state independently, on
  demand, for a T that was never explicitly run. Deferred because it's a real query
  service in its own right (cross-entity traversal, version-chain walking, a new
  `AuditRepository` method beyond today's single-entity `list_for_entity`), not an
  extension of anything P1-8 built.
- **Market-data correction/revision flow**: `uq_market_data_point_commodity_quote_
  delivery` (P1-8) prevents a *duplicate* quote for the same (commodity, quote_date,
  delivery_month), but there's no way to *correct* a quote that was entered wrong --
  today that's a permanent, uncorrectable error (immutability was the deliberate
  choice for reproducibility; see `MarketDataService.add_quote`'s docstring). A real
  correction flow needs its own design: does a correction supersede the original
  (keeping both, like `Trade.previous_version_id`) or truly replace it (breaking any
  already-computed result that used the wrong value)? That's a genuine trade-off
  between reproducibility and correctness, not a small addition -- deferred rather
  than picked hastily.

## 12. Deferred scale/performance work

**Scope**: task P1-9's index/N+1 audit and published benchmarks (`PERFORMANCE.md`,
`ARCHITECTURE.md`'s "Scale and performance") fixed the concrete gaps it found --
missing indexes, an unbounded `GET /trades` limit, an N+1 refresh loop -- but
identified a few real, larger pieces deliberately left for later:

- **Leaner projection queries for bulk trade reads**: `PERFORMANCE.md`'s benchmark
  shows a portfolio-wide `TradeRepository.list_live` at 15,000 rows costs ~6ms for
  the query itself (confirmed via a bare `COUNT(*)`) but ~1.2-1.4s once ORM
  hydration is included -- `Trade.counterparty`/`.book` are `lazy="joined"`, so
  every row eager-joins two more tables even when the caller (e.g.
  `ValuationService.build_positions`, which only touches `volume`/`fixed_price`
  /`buy_sell`/delivery dates) never needs the counterparty's name or the book's
  description. A leaner query -- either a narrower column projection or
  `lazy="selectin"` for bulk-list contexts specifically -- would close this, but
  wasn't speculatively built without a concrete caller actually reaching this
  scale in production; premature optimization here risks solving the wrong shape
  of problem.
- **Timescale compression + retention policies**: `market_data_points` is a bare
  hypertable (Timescale's default 7-day chunking, no `add_compression_policy`/
  `add_retention_policy`). Deferred for the same reason task P1-8's managed-secrets
  item was: this sandbox has no `timescaledb` extension available to validate a
  Timescale-specific migration end-to-end, and a retention period in particular is
  a business/compliance decision (how long must market data be kept?) that
  shouldn't be baked into a migration with an arbitrary default. Also missing:
  continuous aggregates for the "most recent quote per delivery month" pattern
  `MarketDataRepository.latest_quotes` currently recomputes via a full sort +
  Python-side dedup on every call.
- **Real load/concurrency testing**: `PERFORMANCE.md`'s benchmarks measure
  single-request latency at realistic data volumes, not throughput under
  concurrent load -- no connection-pool contention, no simulated multiple traders
  hitting the API at once. `tests/integration/test_limit_concurrency.py` (task
  P0-5) proves *correctness* under genuine concurrent Postgres connections but
  isn't a throughput benchmark. Adopting a real load-testing tool (locust or k6;
  neither is a dependency today) and running it against a docker-compose stack
  would be the natural next step, ideally wired into CI as a non-blocking
  informational job rather than a merge gate (perf numbers are noisy on shared CI
  runners).
- **Async (worker-backed) variants for stress-test/P&L-attribution/option-greeks**:
  these three endpoints run their quant math directly on the request-handling
  event loop with no Arq-backed alternative, unlike curve-build/VaR/delta-ladder
  (see `ARCHITECTURE.md`'s "Async job endpoints"). Not an issue at v1's scale
  (`PERFORMANCE.md` shows all VaR methods finish in single-digit milliseconds at a
  realistic panel), but the natural next candidates once book/scenario sizes grow
  enough that blocking the event loop for their duration becomes noticeable.

## 13. Deferred production-operability, DR, and security work

**Scope**: task P1-10 added CORS policy + baseline security-response headers,
Redis-backed login rate limiting, `ruff`'s bandit (`S`) lint rules, CI dependency
scanning (`pip-audit`, `npm audit`), a container-hardening pass (non-root users,
multi-stage builds, healthchecks, a real production frontend image instead of a
dev server), and a disaster-recovery runbook with an actually-executed backup/
restore drill (`DISASTER_RECOVERY.md`). Real, larger pieces deliberately left for
later:

- **This was a hardening pass, not a third-party security review.** "Security
  review" in this task's name is worth being precise about: what happened here is
  an internal pass against a known checklist (CORS, headers, brute-force
  protection, dependency CVEs, container privilege). It is not a penetration test,
  not a threat-modeling exercise, and not an external audit — none of which a
  single engineering pass can substitute for. Before handling real trading data,
  this platform should get an actual third-party security review.
- **DR runbook's RTO is unset, deliberately** — see `DISASTER_RECOVERY.md`'s "What
  the drill does and doesn't prove": the drill script proves the backup/restore
  *mechanism* round-trips data correctly (including `Decimal` precision) but was
  only run against 3 seed rows on one local machine, which says nothing honest
  about restore time at the 15,000+ trade volumes `PERFORMANCE.md` benchmarks
  against. Re-run the drill's timing against a `benchmark_scale.py`-seeded database
  before publishing a real RTO figure.
- **Cross-server restore, WAL archiving/PITR infrastructure**: also flagged in
  `DISASTER_RECOVERY.md` — this repo has no managed Postgres provider or
  object-storage target yet (Docker Compose is the only deployment target today,
  per `ARCHITECTURE.md`'s "Chosen stack"), so there's nothing to wire continuous
  WAL archiving against. The runbook and a proven dump/restore mechanism exist;
  standing up continuous archiving is "point it at a real target," not "design it
  from scratch."
- **Frontend production image bakes `VITE_API_BASE_URL` in at build time**
  (`frontend/Dockerfile`'s header comment) — correct for Vite (`import.meta.env.*`
  is inlined at compile time, there's no reading it from the container's runtime
  environment), but means one image build per target environment. A
  runtime-config-injection entrypoint (writing a small `config.js` from container
  env vars at container start, read by the app before anything else) would let one
  built image serve every environment; not built here since v1 has exactly one
  deployment target and the extra layer of indirection isn't earning its
  complexity yet.
- **Container image vulnerability scanning** (Trivy/Grype against the built
  images, not just `pip-audit`/`npm audit` against source dependencies) — would
  catch OS-package CVEs in the `python:3.11-slim`/`nginxinc/nginx-unprivileged`
  base images themselves, which dependency-level scanning can't see. Natural next
  step for the `docker-build` CI job once there's an image registry to scan against.
- **`vite`/`vitest`/`esbuild` dev-tooling advisories**: `npm audit` (unscoped)
  currently reports moderate/high/critical findings entirely inside the
  dev-only Vite/Vitest/esbuild build-tooling chain — never bundled into the
  production output, so CI's `dependency-audit` job scopes its blocking check to
  `--omit=dev`. The underlying advisories are still real (a locally-run `vite dev`
  server accepting cross-origin requests, mainly) and worth closing via a Vite
  6/7-major upgrade; deferred here because that's a breaking-change upgrade
  touching the whole toolchain (`vitest` config included) and shouldn't be rushed
  in the same pass as unrelated hardening work.
- **mTLS / network-layer segmentation between services** (api ↔ worker ↔ Postgres
  ↔ Redis) — today's trust boundary is "the network the containers/hosts share,"
  same as most single-tenant deployments at this stage. Worth revisiting alongside
  item 10's managed-secrets-store work once there's a real multi-host deployment
  target to design it against.

## Cross-cutting note

All eight of these want the same two things the rest of the platform already has:
**auth/RBAC** (who can approve a margin call, submit a regulatory report, confirm a
nomination, book an FTR position, or manage a webhook subscription -- reuse
`require_role`) and **an audit trail** (reuse
`app.modules.audit.service.record_audit_event`, following the same "audit entry
commits atomically with the change" pattern `TradeCaptureService` establishes).
Building on those foundations rather than inventing parallel ones is the main
architectural payoff of having built auth/audit first.
