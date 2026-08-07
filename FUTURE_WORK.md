# Future Work: Regulatory Reporting, Credit/Margining, Settlement/Invoicing, Logistics

This is a design sketch, not an implementation plan to execute blindly. Each of these
four areas is a substantial standalone subsystem at a real ETRM vendor, built by teams
with deep regulatory/ops domain expertise. Building any of them to real completeness in
a single pass would mean guessing at requirements (regulatory field formats, CSA/margin
mechanics, GL chart-of-accounts conventions, pipeline nomination protocols) that
genuinely need a domain expert or a specific target jurisdiction/counterparty/pipeline
to get right. What follows is enough to know where each one would attach to the
existing architecture and roughly how big it is, so a future pass has a real starting
point instead of a blank page.

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

## Cross-cutting note

All four of these want the same two things the rest of the platform already has:
**auth/RBAC** (who can approve a margin call, submit a regulatory report, or confirm a
nomination -- reuse `require_role`) and **an audit trail** (reuse
`app.modules.audit.service.record_audit_event`, following the same "audit entry commits
atomically with the change" pattern `TradeCaptureService` establishes). Building on
those foundations rather than inventing parallel ones is the main architectural
payoff of having built auth/audit first.
