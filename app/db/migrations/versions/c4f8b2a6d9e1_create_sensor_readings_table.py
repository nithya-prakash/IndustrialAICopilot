"""create sensor_readings table

Revision ID: c4f8b2a6d9e1
Revises: a7c3d1e9f2b4
Create Date: 2026-08-23 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4f8b2a6d9e1"
down_revision: str | None = "a7c3d1e9f2b4"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "sensor_readings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("equipment_type", sa.String(length=128), nullable=True),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_sensor_readings_tenant_id"), "sensor_readings", ["tenant_id"])
    op.create_index(op.f("ix_sensor_readings_equipment_id"), "sensor_readings", ["equipment_id"])
    op.create_index(
        op.f("ix_sensor_readings_equipment_type"), "sensor_readings", ["equipment_type"]
    )
    op.create_index(op.f("ix_sensor_readings_metric"), "sensor_readings", ["metric"])
    op.create_index(op.f("ix_sensor_readings_recorded_at"), "sensor_readings", ["recorded_at"])
    # The tool signature is query_sensor_history(equipment_id, metric, start_time, end_time) —
    # this composite index matches that access pattern directly.
    op.create_index(
        "ix_sensor_readings_query_pattern",
        "sensor_readings",
        ["tenant_id", "equipment_id", "metric", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sensor_readings_query_pattern", table_name="sensor_readings")
    op.drop_index(op.f("ix_sensor_readings_recorded_at"), table_name="sensor_readings")
    op.drop_index(op.f("ix_sensor_readings_metric"), table_name="sensor_readings")
    op.drop_index(op.f("ix_sensor_readings_equipment_type"), table_name="sensor_readings")
    op.drop_index(op.f("ix_sensor_readings_equipment_id"), table_name="sensor_readings")
    op.drop_index(op.f("ix_sensor_readings_tenant_id"), table_name="sensor_readings")
    op.drop_table("sensor_readings")
