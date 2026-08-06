# OpenETRM

An open source, Apache 2.0 licensed ETRM (Energy Trading & Risk Management) platform.

There is no mature, complete open source ETRM platform today — see
[`ARCHITECTURE.md`](./ARCHITECTURE.md) for the stack decision, the prior art it's built
on (QuantLib, OpenGamma Strata, ORE, `cmdty`), and why Python/FastAPI + React/TypeScript
was chosen.

## What's here (v1)

A vertical slice for a single pilot commodity — **Henry Hub natural gas** financial
swaps/forwards:

- Trade capture (counterparties, books, trades)
- Market data seeding + monthly forward curve bootstrapping
- Mark-to-market valuation and P&L by book
- Historical-simulation VaR and a bucketed delta-ladder sensitivity report

See `ARCHITECTURE.md` for what's deliberately out of scope for v1.

## Quickstart

```bash
docker compose up
```

- API: http://localhost:8000/docs
- Web: http://localhost:5173

To exercise the full flow without the UI, hit the API directly in order: seed a
counterparty and book, book a trade, seed a few market data quotes, build a curve, then
check `/api/v1/positions/{book_id}/pnl` and run `/api/v1/risk/var/run`.

## Local development

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head   # requires postgres+timescaledb running, e.g. via docker compose up postgres
uvicorn app.main:app --reload
```

Tests: `pytest` (integration tests run against an in-memory SQLite DB, no live DB
needed). Lint/type-check: `ruff check app tests`, `ruff format app tests`, `mypy app`.

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
