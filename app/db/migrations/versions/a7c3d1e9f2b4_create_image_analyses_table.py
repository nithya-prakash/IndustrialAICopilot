"""create image_analyses table

Revision ID: a7c3d1e9f2b4
Revises: e2a1c9f4b6d2
Create Date: 2026-08-23 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c3d1e9f2b4"
down_revision: str | None = "e2a1c9f4b6d2"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "image_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("equipment_type", sa.String(length=128), nullable=True),
        sa.Column("equipment_id", sa.String(length=128), nullable=True),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("vision_provider", sa.String(length=32), nullable=False),
        sa.Column("vision_model", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum("analyzing", "ready", "failed", name="image_analysis_status"),
            nullable=False,
        ),
        sa.Column("observations", postgresql.JSONB(), nullable=True),
        sa.Column("limitations", postgresql.JSONB(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(op.f("ix_image_analyses_tenant_id"), "image_analyses", ["tenant_id"])
    op.create_index(
        op.f("ix_image_analyses_equipment_type"), "image_analyses", ["equipment_type"]
    )
    op.create_index(op.f("ix_image_analyses_equipment_id"), "image_analyses", ["equipment_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_image_analyses_equipment_id"), table_name="image_analyses")
    op.drop_index(op.f("ix_image_analyses_equipment_type"), table_name="image_analyses")
    op.drop_index(op.f("ix_image_analyses_tenant_id"), table_name="image_analyses")
    op.drop_table("image_analyses")
    sa.Enum(name="image_analysis_status").drop(op.get_bind(), checkfirst=False)
