"""create equipment, maintenance_tasks, conversations, messages, diagnoses

Revision ID: d8e5f3a1c7b6
Revises: c4f8b2a6d9e1
Create Date: 2026-08-23 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8e5f3a1c7b6"
down_revision: str | None = "c4f8b2a6d9e1"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "equipment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("equipment_type", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("tenant_id", "equipment_id", name="uq_equipment_tenant_id"),
    )
    op.create_index(op.f("ix_equipment_tenant_id"), "equipment", ["tenant_id"])
    op.create_index(op.f("ix_equipment_equipment_type"), "equipment", ["equipment_type"])

    op.create_table(
        "maintenance_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("last_performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(op.f("ix_maintenance_tasks_tenant_id"), "maintenance_tasks", ["tenant_id"])
    op.create_index(
        op.f("ix_maintenance_tasks_equipment_id"), "maintenance_tasks", ["equipment_id"]
    )

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("equipment_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
    )
    op.create_index(op.f("ix_conversations_tenant_id"), "conversations", ["tenant_id"])
    op.create_index(op.f("ix_conversations_equipment_id"), "conversations", ["equipment_id"])

    op.create_table(
        "diagnoses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("equipment_id", sa.String(length=128), nullable=True),
        sa.Column("equipment_type", sa.String(length=128), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.Enum("completed", "failed", name="diagnosis_status"), nullable=False
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("visual_observations", postgresql.JSONB(), nullable=True),
        sa.Column("sensor_findings", postgresql.JSONB(), nullable=True),
        sa.Column("possible_causes", postgresql.JSONB(), nullable=True),
        sa.Column("recommended_checks", postgresql.JSONB(), nullable=True),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum("low", "medium", "high", "critical", name="diagnosis_severity"),
            nullable=False,
        ),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("limitations", postgresql.JSONB(), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column("llm_provider", sa.String(length=32), nullable=False),
        sa.Column("llm_model", sa.String(length=128), nullable=False),
    )
    op.create_index(op.f("ix_diagnoses_tenant_id"), "diagnoses", ["tenant_id"])
    op.create_index(op.f("ix_diagnoses_conversation_id"), "diagnoses", ["conversation_id"])
    op.create_index(op.f("ix_diagnoses_equipment_id"), "diagnoses", ["equipment_id"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Enum("user", "assistant", name="message_role"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "diagnosis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("diagnoses.id"),
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_messages_conversation_id"), "messages", ["conversation_id"])
    op.create_index(op.f("ix_messages_diagnosis_id"), "messages", ["diagnosis_id"])


def downgrade() -> None:
    op.drop_table("messages")
    sa.Enum(name="message_role").drop(op.get_bind(), checkfirst=False)
    op.drop_table("diagnoses")
    sa.Enum(name="diagnosis_severity").drop(op.get_bind(), checkfirst=False)
    sa.Enum(name="diagnosis_status").drop(op.get_bind(), checkfirst=False)
    op.drop_table("conversations")
    op.drop_table("maintenance_tasks")
    op.drop_table("equipment")
