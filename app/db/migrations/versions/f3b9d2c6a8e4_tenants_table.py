"""create tenants table

Revision ID: f3b9d2c6a8e4
Revises: e1f7a4b8c3d5
Create Date: 2026-09-29 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b9d2c6a8e4"
down_revision: str | None = "e1f7a4b8c3d5"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Every tenant that already has users is an existing workspace — backfill
    # them so a new sign-up can't claim one of them as its own.
    op.execute(
        "INSERT INTO tenants (id, created_at) "
        "SELECT tenant_id, MIN(created_at) FROM users GROUP BY tenant_id"
    )


def downgrade() -> None:
    op.drop_table("tenants")
