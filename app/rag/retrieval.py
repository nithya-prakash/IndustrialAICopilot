"""Hybrid retrieval orchestrator.

Query -> [dense (Qdrant) + BM25 (Postgres-scoped)] -> Reciprocal Rank Fusion
-> cross-encoder rerank -> top-k. See docs/architecture-decisions.md for why
each stage exists.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentVersion
from app.rag.bm25 import bm25_search_cached
from app.rag.embeddings import embed_texts
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.qdrant_store import search as qdrant_dense_search
from app.rag.reranker import rerank


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    content: str
    score: float
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    filename: str
    page_number: int | None
    section: str | None
    subsection: str | None
    equipment_type: str | None
    equipment_id: str | None

    @property
    def citation(self) -> str:
        heading = " > ".join(part for part in [self.section, self.subsection] if part)
        pieces = [self.filename]
        if heading:
            pieces.append(heading)
        if self.page_number:
            pieces.append(f"p.{self.page_number}")
        return f"[{', '.join(pieces)}]"


async def _fetch_candidates(
    db: AsyncSession,
    *,
    tenant_id: str,
    equipment_type: str | None,
    equipment_id: str | None,
    document_id: uuid.UUID | None,
):
    query = (
        select(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.page_number,
            DocumentChunk.section,
            DocumentChunk.subsection,
            DocumentChunk.document_version_id,
            DocumentChunk.qdrant_point_id,
            Document.id.label("document_id"),
            Document.original_filename,
            Document.equipment_type,
            Document.equipment_id,
        )
        .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(Document.tenant_id == tenant_id, DocumentVersion.is_current.is_(True))
    )
    if equipment_type:
        query = query.where(Document.equipment_type == equipment_type)
    if equipment_id:
        query = query.where(Document.equipment_id == equipment_id)
    if document_id:
        query = query.where(Document.id == document_id)

    result = await db.execute(query)
    return result.all()


async def get_manual_section(
    db: AsyncSession, *, tenant_id: str, document_id: uuid.UUID, section: str
) -> list[RetrievedChunk]:
    """The literal `get_manual_section` agent tool: a direct lookup by
    document + section/subsection name (case-insensitive substring match),
    not a semantic search — for when the agent already knows which section
    it wants (e.g. after search_technical_documents surfaced it) rather
    than searching again."""
    rows = await _fetch_candidates(
        db, tenant_id=tenant_id, equipment_type=None, equipment_id=None, document_id=document_id
    )
    needle = section.strip().lower()
    matches = [
        row
        for row in rows
        if needle in (row.section or "").lower() or needle in (row.subsection or "").lower()
    ]
    return [
        RetrievedChunk(
            chunk_id=row.id,
            content=row.content,
            score=1.0,
            document_id=row.document_id,
            document_version_id=row.document_version_id,
            filename=row.original_filename,
            page_number=row.page_number,
            section=row.section,
            subsection=row.subsection,
            equipment_type=row.equipment_type,
            equipment_id=row.equipment_id,
        )
        for row in matches
    ]


async def hybrid_search(
    db: AsyncSession,
    query: str,
    *,
    tenant_id: str,
    equipment_type: str | None = None,
    equipment_id: str | None = None,
    document_id: uuid.UUID | None = None,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    settings = get_settings()
    result_limit = top_k if top_k is not None else settings.rerank_top_k

    rows = await _fetch_candidates(
        db,
        tenant_id=tenant_id,
        equipment_type=equipment_type,
        equipment_id=equipment_id,
        document_id=document_id,
    )
    rows_by_id = {str(row.id): row for row in rows}
    if not rows_by_id or not query.strip():
        return []

    # Qdrant is indexed under its own point_id (a uuid4 generated at
    # ingestion time — see app/services/ingestion_service.py), never the
    # same value as DocumentChunk.id. Translate dense results back to
    # DocumentChunk.id via qdrant_point_id so they can actually match
    # rows_by_id below — without this, every dense hit is silently dropped
    # and "hybrid" search degrades to BM25-only (a real bug found and
    # fixed during the Fix Pass evaluation; see the ADR entry).
    chunk_id_by_point_id = {
        row.qdrant_point_id: str(row.id) for row in rows if row.qdrant_point_id
    }

    query_vector = embed_texts([query])[0]
    dense_results = qdrant_dense_search(
        query_vector,
        top_k=settings.dense_top_k,
        tenant_id=tenant_id,
        equipment_type=equipment_type,
        equipment_id=equipment_id,
        document_id=str(document_id) if document_id else None,
    )
    dense_ranked = [
        chunk_id_by_point_id[point_id]
        for point_id, _score, _payload in dense_results
        if point_id in chunk_id_by_point_id
    ]

    corpus = [(str(row.id), row.content) for row in rows]
    bm25_cache_key = (
        tenant_id,
        equipment_type,
        equipment_id,
        str(document_id) if document_id else None,
    )
    bm25_ranked = [
        sc.chunk_id
        for sc in bm25_search_cached(
            query, corpus, top_k=settings.bm25_top_k, cache_key=bm25_cache_key
        )
    ]

    fused = reciprocal_rank_fusion([dense_ranked, bm25_ranked], k=settings.rrf_k)
    fused_ids = [chunk_id for chunk_id, _score in fused if chunk_id in rows_by_id]
    if not fused_ids:
        return []

    rerank_candidates = [(cid, rows_by_id[cid].content) for cid in fused_ids]
    reranked = rerank(query, rerank_candidates)
    top = [
        (cid, score) for cid, score in reranked if score >= settings.min_relevance_score
    ][:result_limit]

    results: list[RetrievedChunk] = []
    for cid, score in top:
        row = rows_by_id[cid]
        results.append(
            RetrievedChunk(
                chunk_id=row.id,
                content=row.content,
                score=score,
                document_id=row.document_id,
                document_version_id=row.document_version_id,
                filename=row.original_filename,
                page_number=row.page_number,
                section=row.section,
                subsection=row.subsection,
                equipment_type=row.equipment_type,
                equipment_id=row.equipment_id,
            )
        )
    return results
