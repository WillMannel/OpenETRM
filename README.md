# OpenETRM

An open source, Apache 2.0 licensed ETRM (Energy Trading & Risk Management) platform.

There is no mature, complete open source ETRM platform today — see
[`ARCHITECTURE.md`](./ARCHITECTURE.md) for the stack decision, the prior art it's built
on (QuantLib, OpenGamma Strata, ORE, `cmdty`), and why Python/FastAPI + React/TypeScript
was chosen.

## What's here (v1)

A vertical slice covering **Henry Hub natural gas**, **WTI crude oil**, **coal**, and
**power** (single-hub, peak/off-peak blocks), plus two environmental certificate
products (**RECs**, **emissions allowances**):

- Auth (JWT), RBAC (VIEWER/TRADER/RISK_MANAGER/ADMIN), and an audit trail on every
  trade lifecycle transition
- Trade capture with a real lifecycle: capture → confirm → amend/cancel through
  four-eyes approval, for swaps/forwards, options (Black-76 pricing, per-trade
  greeks), and vintage-tracked RECs/emissions allowances
- Market data seeding + monthly forward curve bootstrapping
- Mark-to-market valuation and P&L by book
- Risk: VaR (historical simulation, parametric, or Monte Carlo), a bucketed
  delta-ladder, stress testing, P&L attribution, and option greeks
- Position/risk limits: pre-trade volume limits (blocking) and VaR limits (alerting),
  with breach tracking and acknowledgement
- Observability: structured JSON logs with per-request correlation ids, Prometheus
  metrics (`/metrics`), and a liveness/readiness health split
- Integrations: a read-only reporting-views role for direct BI/pipeline connections
  (Microsoft Fabric, Power BI, Databricks, Snowflake) and REST bulk-export endpoints
  (CSV/JSON/Parquet) with API-key auth for service accounts — see `INTEGRATIONS.md`
- Production hardening: CORS + security-response headers, Redis-backed login
  rate limiting, non-root/multi-stage container images, CI dependency-vulnerability
  scanning, and a backup/restore runbook with an actually-executed DR drill — see
  `DISASTER_RECOVERY.md`

See `ARCHITECTURE.md` for the details and `FUTURE_WORK.md` for what's deliberately out
of scope (regulatory reporting, credit/margining, settlement/invoicing, logistics,
multi-hub/basis power trading, FTRs, behind-the-meter PPA economics, outbound
webhooks, a native OneLake write path).

## Quickstart

```bash
docker compose up
```

- API: http://localhost:8000/docs
- Web: http://localhost:5173

The first thing anyone needs is an account. Register a VIEWER via the web app's
"Register" link (or `POST /auth/register`), then provision your own admin:

```bash
docker compose exec api python scripts/create_admin.py <username> <email> <password>
```

Log in as that admin, then use `POST /auth/users` (or the browser's dev tools /
`/docs` UI) to provision TRADER/RISK_MANAGER accounts for testing the full lifecycle.

To exercise the full flow without the UI: log in, seed a counterparty and book, book a
trade (TRADER), confirm it (RISK_MANAGER), seed a few market data quotes, build a
curve, then check `/api/v1/positions/{book_id}/pnl` and run `/api/v1/risk/var/run`.

Connecting a BI/pipeline tool (Fabric, Power BI, Databricks, Snowflake)? See
`INTEGRATIONS.md`. Quick version:

```bash
docker compose exec api python scripts/create_reporting_role.py <role_name> <password>
```

## Local development

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head   # requires postgres+timescaledb running, e.g. via docker compose up postgres
uvicorn app.main:app --reload
python scripts/create_admin.py <username> <email> <password>   # bootstrap the first admin
```

Tests: `pytest` (integration tests run against an in-memory SQLite DB, no live DB
needed; worker end-to-end tests are skipped unless `RUN_WORKER_E2E_TESTS=1` with real
`DATABASE_URL`/`REDIS_URL` set). Lint/type-check: `ruff check app tests`,
`ruff format app tests`, `mypy app`.

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

Tests: `npx vitest run`. Type-check + build: `npm run build`. The typed API client is
generated from the backend's OpenAPI schema — regenerate it with
`npm run generate-api-types` after changing backend request/response models (backend
must be running on :8000).

## License

Apache 2.0 — see [`LICENSE`](./LICENSE).
