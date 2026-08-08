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
model that silently mis-prices real risk) is worse than not having them.

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

## Cross-cutting note

All seven of these want the same two things the rest of the platform already has:
**auth/RBAC** (who can approve a margin call, submit a regulatory report, confirm a
nomination, or book an FTR position -- reuse `require_role`) and **an audit trail**
(reuse `app.modules.audit.service.record_audit_event`, following the same "audit entry
commits atomically with the change" pattern `TradeCaptureService` establishes).
Building on those foundations rather than inventing parallel ones is the main
architectural payoff of having built auth/audit first.
