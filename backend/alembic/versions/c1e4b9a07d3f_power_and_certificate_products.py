"""power (peak/off-peak block) and environmental certificate (REC/emissions) trades

Revision ID: c1e4b9a07d3f
Revises: 9d3a7e2c5f81
Create Date: 2026-08-08

Adds power_block/certificate_registry/vintage_year columns on trades. Commodity.COAL/POWER,
TradeType.REC/EMISSIONS_ALLOWANCE, and VolumeUnit.MWH/METRIC_TON are plain-string enum
values stored in existing VARCHAR columns, so those need no schema change of their
own -- only the new fields those trade shapes carry. Table shape verified the same way
as prior migrations: compiling the new columns' DDL against the postgres dialect
offline before writing this by hand.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1e4b9a07d3f"
down_revision: str | None = "9d3a7e2c5f81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("power_block", sa.String(10), nullable=True))
    op.add_column("trades", sa.Column("certificate_registry", sa.String(50), nullable=True))
    op.add_column("trades", sa.Column("vintage_year", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("trades", "vintage_year")
    op.drop_column("trades", "certificate_registry")
    op.drop_column("trades", "power_block")
