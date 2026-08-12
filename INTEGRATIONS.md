# Integrations

OpenETRM exposes two supported paths for getting trade/position/valuation/risk data
into an external analytics or BI platform — Microsoft Fabric, Power BI, Databricks,
Snowflake, or anything else that either speaks SQL to Postgres or can call a REST API.
Both are read-only from the external tool's perspective; neither lets an outside
system write back into OpenETRM.

## 1. Direct Postgres connector (recommended)

Fabric (Dataflow Gen2 and Data Factory pipelines), Power BI, Databricks, and Snowflake
all ship a native PostgreSQL connector. The lowest-latency, always-current integration
is simply pointing one of those at a dedicated read-only role scoped to a set of
flattened reporting views — no extra infrastructure, no polling delay.

**Provisioning**: `python scripts/create_reporting_role.py <role_name> <password>`
creates the role (or refreshes its grants if it already exists) and grants `SELECT`
on the views below — nothing else. It never grants access to the base tables, which
would expose `users.hashed_password` / `api_keys.hashed_key` and every other module's
raw data this role has no business seeing; least-privilege by construction, not by
convention.

**Desk separation note**: this role is intentionally a single, shared,
enterprise-wide read role — it doesn't authenticate as an individual OpenETRM user, so
the book-level entitlements/desk walls `app.modules.entitlements` enforces at the API
layer (see `ARCHITECTURE.md`) do **not** apply here: a connection through this role
sees every book's rows in every view, walled or not. If a deployment needs row-level
desk separation in its BI tool too, that's a deferred, buildable extension (per-desk
Postgres roles + row-level-security policies) — see `FUTURE_WORK.md` §9.

**Views** (`alembic/versions/..._reporting_views.py`), all in the `public` schema:

| View | Grain | Notes |
|---|---|---|
| `v_trades_flat` | one row per trade version | counterparty/book already joined in by name |
| `v_positions_flat` | one row per book × commodity × delivery month, latest valuation run only | superseded runs for the same book/commodity/as-of-date are excluded, not just the newest row kept ambiguously — see `valuation_runs` |
| `v_valuation_results_flat` | one row per book leg or option trade, latest valuation run only | same latest-run-only scoping as `v_positions_flat` |
| `v_var_results_flat` | one row per VaR run | |
| `v_audit_log_flat` | one row per lifecycle event | omits the `before`/`after` JSON columns on purpose — most BI tools handle a flat schema far better than nested JSON per row |

**Fabric specifics**: in a Dataflow Gen2 or a Data Factory pipeline's Copy activity,
add a PostgreSQL connection using the role's credentials and your deployment's
host/port/database. The `v_*_flat` views show up in the table picker like any other
table and can be loaded into a Lakehouse or Warehouse on whatever refresh schedule the
pipeline runs.

**Power BI**: Get Data → PostgreSQL database → same role and views, either Import or
DirectQuery.

**Databricks**: the Postgres JDBC connector, same role/views, as an external data
source or via `CREATE TABLE ... USING org.postgresql.Driver`.

**Snowflake**: no native Postgres connector, so this goes through an intermediate
(Fivetran, Airbyte, or Snowflake's own Postgres connector where available) pointed at
the same role — Snowflake is the one platform in this list where the REST path below
may end up simpler in practice.

## 2. REST export endpoints + API key

For tools that call HTTP APIs rather than connecting to a database directly — a
Fabric Data Factory "Web"/REST activity, or any deployment where the BI/pipeline
tool's network can't reach the database (a common constraint when the tool runs in a
different cloud/VNet than the database).

**Authentication**: provision a service-account user
(`POST /auth/users`, ADMIN-only, typically role `VIEWER` since these endpoints are
read-only) and mint an API key for it
(`POST /auth/users/{user_id}/api-keys`, ADMIN-only) — the raw key
(`oetrm_...`) is returned exactly once, in that response, and can't be retrieved
again, only revoked (`POST /auth/api-keys/{id}/revoke`). Send it as
`X-API-Key: oetrm_...` on every request instead of an `Authorization: Bearer` JWT —
`get_current_user` accepts either, resolving an API key to its associated
service-account user so every existing RBAC rule applies unchanged.

**Endpoints** (`app/modules/export/router.py`), all under `/api/v1/export`:

| Endpoint | Filters | Notes |
|---|---|---|
| `GET /export/trades` | `book_id`, `updated_since`, `limit`, `offset` | |
| `GET /export/positions` | `as_of_date` (required), `book_id` | positions are recomputed per valuation run, not updated in place — `as_of_date` selects which snapshot, there's no `updated_since` |
| `GET /export/valuation-results` | `book_id`, `updated_since`, `limit`, `offset` | |
| `GET /export/var-results` | `book_id`, `updated_since`, `limit`, `offset` | |

Every endpoint takes `format=csv|json|parquet` (default `csv`). Parquet specifically
because that's the format [OneLake](https://learn.microsoft.com/fabric/onelake/onelake-overview)
(Fabric's lake) speaks — OneLake exposes the ADLS Gen2 API, so a Fabric pipeline's
Copy Data activity with a REST/HTTP source pointed at one of these endpoints and a
Lakehouse destination lands the data as a Delta table without any extra conversion
step. `updated_since` (an ISO 8601 timestamp) makes incremental pulls possible instead
of a full re-extract on every run — pass the previous run's completion time.

## Choosing between them

- **Direct DB connector** — lower latency, always current, nothing to schedule beyond
  what the BI tool already does. Default recommendation whenever the tool's network
  can reach the database.
- **REST export** — works over the public internet without opening database access,
  gives every caller the identical stable contract regardless of which tool is
  asking, and is the only option when direct DB access isn't possible. Costs an extra
  hop and whatever polling/scheduling cadence the pipeline runs at.

## Authentication summary

| Method | Header / credential | Who uses it |
|---|---|---|
| JWT bearer | `Authorization: Bearer <token>` | Interactive users — the web app, `/docs` |
| API key | `X-API-Key: oetrm_...` | Service accounts calling `/export/*` or any other endpoint |
| Postgres role | connection credentials | Direct-connector BI/pipeline tools, `v_*_flat` views only |

## What's not built here

Two things would make this a tighter Fabric integration and are deliberately not
attempted yet — see `FUTURE_WORK.md` for the design sketch of each: **outbound
webhooks** (near-real-time push on trade lifecycle events, for Fabric
Eventstream/Data Activator or any other event-driven consumer, instead of the pull
model above) and **a native OneLake write path** (this service pushing Parquet
directly to a OneLake ADLS Gen2 endpoint on a schedule, rather than waiting to be
pulled from). Both need a real Fabric/Azure tenant to build against and verify, which
this environment doesn't have.
