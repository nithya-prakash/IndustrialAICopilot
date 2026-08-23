"""add tenant_id to users, create documents/document_versions/document_chunks

Revision ID: e2a1c9f4b6d2
Revises: b49093617918
Create Date: 2026-08-23 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2a1c9f4b6d2"
down_revision: str | None = "b49093617918"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
    )
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("equipment_type", sa.String(length=128), nullable=True),
        sa.Column("equipment_id", sa.String(length=128), nullable=True),
    )
    op.create_index(op.f("ix_documents_tenant_id"), "documents", ["tenant_id"])
    op.create_index(op.f("ix_documents_equipment_type"), "documents", ["equipment_type"])
    op.create_index(op.f("ix_documents_equipment_id"), "documents", ["equipment_id"])

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "processing",
                "extracting",
                "ocr",
                "chunking",
                "embedding",
                "indexing",
                "ready",
                "failed",
                name="document_status",
            ),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("used_ocr", sa.Boolean(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_version"),
    )
    op.create_index(op.f("ix_document_versions_document_id"), "document_versions", ["document_id"])
    op.create_index(op.f("ix_document_versions_is_current"), "document_versions", ["is_current"])

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=256), nullable=True),
        sa.Column("subsection", sa.String(length=256), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("qdrant_point_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_document_chunks_document_version_id"), "document_chunks", ["document_version_id"]
    )
    op.create_index(
        op.f("ix_document_chunks_qdrant_point_id"), "document_chunks", ["qdrant_point_id"]
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("document_versions")
    sa.Enum(name="document_status").drop(op.get_bind(), checkfirst=False)
    op.drop_index(op.f("ix_documents_equipment_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_equipment_type"), table_name="documents")
    op.drop_index(op.f("ix_documents_tenant_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_column("users", "tenant_id")
