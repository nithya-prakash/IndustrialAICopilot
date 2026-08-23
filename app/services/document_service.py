import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentStatus, DocumentVersion
from app.rag.qdrant_store import delete_by_document_version, set_current_flag
from app.services.audit_service import log_event
from app.tasks.ingestion_tasks import process_document_version_task

PDF_MAGIC = b"%PDF-"


class UnsupportedFileTypeError(Exception):
    pass


class FileTooLargeError(Exception):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        super().__init__(f"File exceeds max size of {max_bytes} bytes")


class InvalidFileContentError(Exception):
    pass


class DocumentNotFoundError(Exception):
    pass


async def _read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FileTooLargeError(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


async def upload_document(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    tenant_id: str,
    file: UploadFile,
    equipment_type: str | None,
    equipment_id: str | None,
    document_id: uuid.UUID | None,
) -> tuple[Document, DocumentVersion]:
    settings = get_settings()

    if file.content_type not in settings.allowed_upload_content_types_list:
        raise UnsupportedFileTypeError(file.content_type)

    content = await _read_upload_within_limit(file, settings.max_upload_size_bytes)
    if not content.startswith(PDF_MAGIC):
        raise InvalidFileContentError("File content does not look like a valid PDF")

    return await create_document_version(
        db,
        owner_id=owner_id,
        tenant_id=tenant_id,
        filename=file.filename or "upload.pdf",
        content_type=file.content_type,
        content=content,
        equipment_type=equipment_type,
        equipment_id=equipment_id,
        document_id=document_id,
        dispatch_processing=True,
    )


async def create_document_version(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    tenant_id: str,
    filename: str,
    content_type: str,
    content: bytes,
    equipment_type: str | None,
    equipment_id: str | None,
    document_id: uuid.UUID | None,
    dispatch_processing: bool = True,
) -> tuple[Document, DocumentVersion]:
    """Lower-level entry point used by the upload API (after reading and
    validating an UploadFile) and by the evaluation runner (which builds a
    fixture document directly from bytes, with no HTTP request involved)."""
    settings = get_settings()

    if document_id is not None:
        document = await get_document(db, document_id=document_id, tenant_id=tenant_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        next_version_number = (
            max((v.version_number for v in document.versions), default=0) + 1
        )
        for existing in document.versions:
            existing.is_current = False
            set_current_flag(str(existing.id), is_current=False)
    else:
        document = Document(
            tenant_id=tenant_id,
            owner_id=owner_id,
            original_filename=filename,
            equipment_type=equipment_type,
            equipment_id=equipment_id,
        )
        db.add(document)
        await db.flush()
        next_version_number = 1

    version_id = uuid.uuid4()
    storage_dir = Path(settings.data_dir) / "manuals"
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / f"{version_id}.pdf"
    storage_path.write_bytes(content)

    version = DocumentVersion(
        id=version_id,
        document_id=document.id,
        version_number=next_version_number,
        storage_path=str(storage_path),
        content_type=content_type,
        file_size_bytes=len(content),
        status=DocumentStatus.uploaded,
        is_current=True,
    )
    db.add(version)
    await db.flush()
    await log_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=owner_id,
        action="document.uploaded",
        resource_type="document",
        resource_id=document.id,
        detail={"filename": filename, "version_number": next_version_number},
    )
    await db.commit()
    await db.refresh(document)
    await db.refresh(version)

    if dispatch_processing:
        process_document_version_task.delay(str(version.id))

    return document, version


async def list_documents(
    db: AsyncSession,
    *,
    tenant_id: str,
    equipment_type: str | None = None,
    equipment_id: str | None = None,
) -> list[tuple[Document, DocumentVersion | None, int]]:
    query = (
        select(Document)
        .options(selectinload(Document.versions).selectinload(DocumentVersion.chunks))
        .where(Document.tenant_id == tenant_id)
        .order_by(Document.created_at.desc())
    )
    if equipment_type:
        query = query.where(Document.equipment_type == equipment_type)
    if equipment_id:
        query = query.where(Document.equipment_id == equipment_id)

    result = await db.execute(query)
    documents = result.scalars().unique().all()

    rows: list[tuple[Document, DocumentVersion | None, int]] = []
    for document in documents:
        current = next((v for v in document.versions if v.is_current), None)
        chunk_count = len(current.chunks) if current else 0
        rows.append((document, current, chunk_count))
    return rows


async def get_document(
    db: AsyncSession, *, document_id: uuid.UUID, tenant_id: str
) -> Document | None:
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.versions).selectinload(DocumentVersion.chunks))
        .where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def delete_document(
    db: AsyncSession, *, document_id: uuid.UUID, tenant_id: str, actor_user_id: uuid.UUID
) -> None:
    document = await get_document(db, document_id=document_id, tenant_id=tenant_id)
    if document is None:
        raise DocumentNotFoundError(str(document_id))

    filename = document.original_filename
    for version in document.versions:
        delete_by_document_version(str(version.id))
        path = Path(version.storage_path)
        if path.exists():
            path.unlink()

    await db.delete(document)
    await log_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="document.deleted",
        resource_type="document",
        resource_id=document_id,
        detail={"filename": filename},
    )
    await db.commit()


async def count_chunks(db: AsyncSession, *, document_version_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_version_id == document_version_id)
    )
    return result.scalar_one()
