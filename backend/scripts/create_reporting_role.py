"""Bootstrap a read-only Postgres role scoped to the reporting views -- the direct-
connect integration path for BI/pipeline tools with a native Postgres connector
(Microsoft Fabric, Power BI, Databricks, Snowflake external tables, ...). See
INTEGRATIONS.md for how to point each of those at this role.

Grants SELECT on the v_*_flat views only (see alembic/versions/..._reporting_views.py)
-- never on the underlying tables, which would expose hashed_password/hashed_key
columns and every other module's raw data this role has no business seeing.

Usage:
    python scripts/create_reporting_role.py <role_name> <password>

Safe to re-run: if the role already exists, only its grants are refreshed (its
password is left alone -- rotate it separately with ALTER ROLE if needed).
"""

import asyncio
import re
import sys

from sqlalchemy import text

from app.core.db import engine

# Postgres role names can't be bind parameters (they're identifiers, not values), so
# this is validated against a strict allowlist pattern before ever being interpolated
# into SQL text -- anything that doesn't match is rejected outright, not escaped.
_VALID_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{2,62}$")

_REPORTING_VIEWS = [
    "v_trades_flat",
    "v_positions_flat",
    "v_valuation_results_flat",
    "v_var_results_flat",
    "v_audit_log_flat",
]


def _sql_string_literal(value: str) -> str:
    """CREATE ROLE ... PASSWORD doesn't accept a bind parameter in its grammar (it
    wants a literal), so the password is escaped as one by hand -- doubling embedded
    single quotes is standard SQL string-literal escaping and is injection-safe."""
    return "'" + value.replace("'", "''") + "'"


async def main(role_name: str, password: str) -> None:
    if not _VALID_ROLE_NAME.match(role_name):
        print(f"invalid role name {role_name!r} -- must match {_VALID_ROLE_NAME.pattern}")
        sys.exit(1)

    async with engine.begin() as conn:
        exists = await conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role_name"), {"role_name": role_name}
        )
        if exists.first() is not None:
            print(f"role {role_name!r} already exists -- refreshing its grants only")
        else:
            await conn.execute(
                text(f"CREATE ROLE {role_name} WITH LOGIN PASSWORD {_sql_string_literal(password)}")
            )
            print(f"created role {role_name!r}")

        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role_name}"))
        for view in _REPORTING_VIEWS:
            await conn.execute(text(f"GRANT SELECT ON {view} TO {role_name}"))
        print(f"granted SELECT on {', '.join(_REPORTING_VIEWS)} to {role_name!r}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
