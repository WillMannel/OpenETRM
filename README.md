# OpenETRM

An open source, Apache 2.0 licensed ETRM (Energy Trading & Risk Management) platform.

There is no mature, complete open source ETRM platform today — see
[`ARCHITECTURE.md`](./ARCHITECTURE.md) for the stack decision, the prior art it's built
on (QuantLib, OpenGamma Strata, ORE, `cmdty`), and why Python/FastAPI + React/TypeScript
was chosen.

## What's here (v1)

A vertical slice for two pilot commodities — **Henry Hub natural gas** and **WTI
crude oil** — financial swaps/forwards:

- Auth (JWT), RBAC (VIEWER/TRADER/RISK_MANAGER/ADMIN), and an audit trail on every
  trade lifecycle transition
- Trade capture with a real lifecycle: capture → confirm → amend/cancel through
  four-eyes approval
- Market data seeding + monthly forward curve bootstrapping
- Mark-to-market valuation and P&L by book
- Risk: VaR (historical simulation, parametric, or Monte Carlo), a bucketed
  delta-ladder, stress testing, and P&L attribution

See `ARCHITECTURE.md` for the details and `FUTURE_WORK.md` for what's deliberately out
of scope (regulatory reporting, credit/margining, settlement/invoicing, logistics).

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
