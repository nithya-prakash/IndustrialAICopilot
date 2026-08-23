import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.ingestion.chunker import chunk_blocks
from app.ingestion.ocr import ocr_pages
from app.ingestion.pdf_extractor import ExtractedBlock, extract_pdf
from app.logging_config import get_logger
from app.models.document import DocumentChunk, DocumentStatus, DocumentVersion
from app.rag.embeddings import embed_texts
from app.rag.qdrant_store import ensure_collection, upsert_chunks

logger = get_logger("ingestion")


async def _load_version(db: AsyncSession, version_id: uuid.UUID) -> DocumentVersion:
    result = await db.execute(
        select(DocumentVersion)
        .options(selectinload(DocumentVersion.document))
        .where(DocumentVersion.id == version_id)
    )
    return result.scalar_one()


def _merge_ocr_blocks(
    blocks: list[ExtractedBlock], low_text_pages: list[int], ocr_blocks: list[ExtractedBlock]
) -> list[ExtractedBlock]:
    """Replace the (near-empty/garbage) extracted blocks on scanned pages with
    the OCR'd blocks, keeping everything in page order."""
    ocr_page_set = set(low_text_pages)
    kept = [b for b in blocks if b.page_number not in ocr_page_set]
    merged = kept + ocr_blocks
    merged.sort(key=lambda b: b.page_number)
    return merged


async def process_document_version(version_id: uuid.UUID) -> None:
    settings = get_settings()

    async with AsyncSessionLocal() as db:
        version = await _load_version(db, version_id)
        path = Path(version.storage_path)

        try:
            version.status = DocumentStatus.processing
            await db.commit()

            version.status = DocumentStatus.extracting
            await db.commit()
            extraction = extract_pdf(path)
            blocks = extraction.blocks
            used_ocr = False

            if extraction.low_text_pages:
                version.status = DocumentStatus.ocr
                await db.commit()
                ocr_blocks = ocr_pages(path, extraction.low_text_pages)
                blocks = _merge_ocr_blocks(blocks, extraction.low_text_pages, ocr_blocks)
                used_ocr = True

            version.status = DocumentStatus.chunking
            await db.commit()
            chunks = chunk_blocks(blocks, settings.chunk_target_chars, settings.chunk_overlap_chars)

            if not chunks:
                version.status = DocumentStatus.failed
                version.error_message = "No extractable text found in document"
                version.page_count = extraction.page_count
                version.used_ocr = used_ocr
                await db.commit()
                logger.error("ingestion_no_text", document_version_id=str(version_id))
                return

            version.status = DocumentStatus.embedding
            await db.commit()
            vectors = embed_texts([c.content for c in chunks])

            version.status = DocumentStatus.indexing
            await db.commit()
            ensure_collection()

            document = version.document
            points: list[tuple[str, list[float], dict]] = []
            chunk_rows: list[DocumentChunk] = []
            for chunk, vector in zip(chunks, vectors, strict=True):
                point_id = str(uuid.uuid4())
                payload = {
                    "tenant_id": document.tenant_id,
                    "document_id": str(document.id),
                    "document_version_id": str(version.id),
                    "version_number": version.version_number,
                    "filename": document.original_filename,
                    "page_number": chunk.page_number,
                    "section": chunk.section,
                    "subsection": chunk.subsection,
                    "equipment_type": document.equipment_type,
                    "equipment_id": document.equipment_id,
                    "chunk_id": point_id,
                    "content": chunk.content,
                    "is_current": version.is_current,
                }
                points.append((point_id, vector, payload))
                chunk_rows.append(
                    DocumentChunk(
                        document_version_id=version.id,
                        chunk_index=chunk.chunk_index,
                        page_number=chunk.page_number,
                        section=chunk.section,
                        subsection=chunk.subsection,
                        content=chunk.content,
                        qdrant_point_id=point_id,
                    )
                )

            upsert_chunks(points)
            db.add_all(chunk_rows)

            version.status = DocumentStatus.ready
            version.page_count = extraction.page_count
            version.used_ocr = used_ocr
            await db.commit()
            logger.info(
                "ingestion_ready",
                document_version_id=str(version_id),
                chunk_count=len(chunk_rows),
                used_ocr=used_ocr,
            )

        except Exception as exc:
            await db.rollback()
            async with AsyncSessionLocal() as error_db:
                error_version = await error_db.get(DocumentVersion, version_id)
                if error_version is not None:
                    error_version.status = DocumentStatus.failed
                    error_version.error_message = str(exc)[:2000]
                    await error_db.commit()
            logger.error("ingestion_failed", document_version_id=str(version_id), error=str(exc))
            raise


def process_document_version_sync(version_id: str) -> None:
    asyncio.run(process_document_version(uuid.UUID(version_id)))
