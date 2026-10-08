"""add per-diagnosis LLM usage

Revision ID: a7c4e1d9b2f6
Revises: f3b9d2c6a8e4
Create Date: 2026-10-08 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c4e1d9b2f6"
down_revision: str | None = "f3b9d2c6a8e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("diagnoses", sa.Column("usage", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("diagnoses", "usage")
