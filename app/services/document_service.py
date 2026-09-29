import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.filenames import sanitize_display_filename
from app.logging_config import get_logger
from app.models.document import Document, DocumentChunk, DocumentStatus, DocumentVersion
from app.rag.bm25 import invalidate_bm25_cache
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

    # Postgres is the source of truth for which version is current (dense
    # Qdrant hits are only used if they match a current-version chunk row —
    # see app/rag/retrieval.py), so Qdrant is only updated *after* the
    # commit below. A failed commit then leaves Qdrant untouched instead of
    # half-superseded.
    superseded_version_ids: list[str] = []
    if document_id is not None:
        document = await get_document(db, document_id=document_id, tenant_id=tenant_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        next_version_number = (
            max((v.version_number for v in document.versions), default=0) + 1
        )
        for existing in document.versions:
            if existing.is_current:
                superseded_version_ids.append(str(existing.id))
            existing.is_current = False
    else:
        document = Document(
            tenant_id=tenant_id,
            owner_id=owner_id,
            original_filename=sanitize_display_filename(filename),
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

    try:
        version = await _record_version(
            db,
            document=document,
            version_id=version_id,
            version_number=next_version_number,
            storage_path=storage_path,
            content_type=content_type,
            content=content,
            tenant_id=tenant_id,
            owner_id=owner_id,
            filename=filename,
        )
    except Exception:
        # Nothing references the file if the DB write didn't land — don't
        # leave an orphaned PDF behind in data/manuals/.
        await db.rollback()
        storage_path.unlink(missing_ok=True)
        raise

    for old_version_id in superseded_version_ids:
        try:
            set_current_flag(old_version_id, is_current=False)
        except Exception as exc:  # noqa: BLE001 - see the ordering note above
            get_logger().warning(
                "qdrant_current_flag_update_failed",
                document_version_id=old_version_id,
                error=str(exc),
            )

    if dispatch_processing:
        process_document_version_task.delay(str(version.id))

    return document, version


async def _record_version(
    db: AsyncSession,
    *,
    document: Document,
    version_id: uuid.UUID,
    version_number: int,
    storage_path: Path,
    content_type: str,
    content: bytes,
    tenant_id: str,
    owner_id: uuid.UUID,
    filename: str,
) -> DocumentVersion:
    version = DocumentVersion(
        id=version_id,
        document_id=document.id,
        version_number=version_number,
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
        detail={"filename": filename, "version_number": version_number},
    )
    await db.commit()
    await db.refresh(document)
    await db.refresh(version)
    return version


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
    versions = [(str(v.id), Path(v.storage_path)) for v in document.versions]

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

    # Only once the DB delete has committed: removing the files and vectors
    # first meant a failed commit left a document that still listed as
    # "ready" but had no PDF and no embeddings. Cleanup failures now only
    # leave unreferenced leftovers (retrieval never uses a vector without a
    # matching chunk row), logged for manual cleanup.
    for version_id, path in versions:
        try:
            delete_by_document_version(version_id)
        except Exception as exc:  # noqa: BLE001 - the delete itself already succeeded
            get_logger().warning(
                "qdrant_cleanup_failed", document_version_id=version_id, error=str(exc)
            )
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            get_logger().warning("file_cleanup_failed", path=str(path), error=str(exc))

    # Same process as the BM25 index cache (app/rag/bm25.py) — a deletion
    # can invalidate it immediately rather than waiting out the TTL, unlike
    # ingestion completions, which happen in the separate Celery worker.
    invalidate_bm25_cache()


async def count_chunks(db: AsyncSession, *, document_version_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_version_id == document_version_id)
    )
    return result.scalar_one()
