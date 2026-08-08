"""read-only reporting views for direct BI/pipeline connections

Revision ID: a7c2e9f14d68
Revises: f3a8d1c6e4b2
Create Date: 2026-08-08

Flattened, denormalized views over the base tables -- the direct-Postgres-connector
integration path for tools with a native one (Microsoft Fabric, Power BI, Databricks,
Snowflake external tables, ...; see INTEGRATIONS.md). Deliberately expose only these
views to the read-only role scripts/create_reporting_role.py provisions, never the
base tables directly -- `users`/`api_keys` carry hashed credentials that role must
never see, and every view here was written to leave those tables out entirely.

v_audit_log_flat omits the before/after JSONB columns on purpose: they're
arbitrary-shaped per entity_type and most BI/pipeline tools handle a flat schema far
better than nested JSON. A future v_audit_log_detail view can add them back if a
specific integration needs the full diff.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c2e9f14d68"
down_revision: str | None = "f3a8d1c6e4b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VIEWS: dict[str, str] = {
    "v_trades_flat": """
        SELECT
            t.id,
            t.trade_date,
            c.name AS counterparty_name,
            b.name AS book_name,
            t.commodity,
            t.trade_type,
            t.buy_sell,
            t.volume,
            t.volume_unit,
            t.fixed_price,
            t.price_currency,
            t.delivery_start_month,
            t.delivery_end_month,
            t.power_block,
            t.option_type,
            t.strike_price,
            t.premium,
            t.option_volatility,
            t.certificate_registry,
            t.vintage_year,
            t.status,
            t.version,
            t.previous_version_id,
            t.created_at,
            t.updated_at
        FROM trades t
        JOIN counterparties c ON c.id = t.counterparty_id
        JOIN books b ON b.id = t.book_id
    """,
    "v_positions_flat": """
        SELECT
            p.id,
            b.name AS book_name,
            p.commodity,
            p.delivery_month,
            p.net_volume,
            p.avg_fixed_price,
            p.as_of_date
        FROM positions p
        JOIN books b ON b.id = p.book_id
    """,
    "v_valuation_results_flat": """
        SELECT
            v.id,
            v.trade_id,
            b.name AS book_name,
            v.as_of_date,
            v.mtm_value,
            v.realized_pnl,
            v.unrealized_pnl,
            v.currency,
            v.computed_at
        FROM valuation_results v
        LEFT JOIN books b ON b.id = v.book_id
    """,
    "v_var_results_flat": """
        SELECT
            r.id,
            b.name AS book_name,
            r.as_of_date,
            r.confidence_level,
            r.horizon_days,
            r.method,
            r.scenario_window_days,
            r.var_value,
            r.computed_at
        FROM var_results r
        LEFT JOIN books b ON b.id = r.book_id
    """,
    "v_audit_log_flat": """
        SELECT
            a.id,
            a.entity_type,
            a.entity_id,
            a.action,
            u.username AS actor_username,
            a.occurred_at,
            a.note
        FROM audit_log a
        LEFT JOIN users u ON u.id = a.actor_user_id
    """,
}


def upgrade() -> None:
    for name, query in _VIEWS.items():
        op.execute(f"CREATE VIEW {name} AS{query}")


def downgrade() -> None:
    for name in reversed(list(_VIEWS)):
        op.execute(f"DROP VIEW {name}")
