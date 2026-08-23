"""create approvals and audit_logs tables

Revision ID: e1f7a4b8c3d5
Revises: d8e5f3a1c7b6
Create Date: 2026-08-23 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f7a4b8c3d5"
down_revision: str | None = "d8e5f3a1c7b6"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "diagnosis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("diagnoses.id"),
            nullable=False,
        ),
        sa.Column(
            "supervisor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "decision", sa.Enum("approved", "rejected", name="approval_decision"), nullable=False
        ),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.UniqueConstraint("diagnosis_id", name="uq_approval_diagnosis_id"),
    )
    op.create_index(op.f("ix_approvals_tenant_id"), "approvals", ["tenant_id"])
    op.create_index(op.f("ix_approvals_diagnosis_id"), "approvals", ["diagnosis_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
    )
    op.create_index(op.f("ix_audit_logs_tenant_id"), "audit_logs", ["tenant_id"])
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
    op.create_index(op.f("ix_audit_logs_resource_type"), "audit_logs", ["resource_type"])
    op.create_index(op.f("ix_audit_logs_resource_id"), "audit_logs", ["resource_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("approvals")
    sa.Enum(name="approval_decision").drop(op.get_bind(), checkfirst=False)
