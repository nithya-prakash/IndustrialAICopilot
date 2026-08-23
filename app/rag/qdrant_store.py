from functools import lru_cache
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config import get_settings


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def ensure_collection() -> None:
    settings = get_settings()
    client = get_qdrant_client()
    if not client.collection_exists(settings.qdrant_collection):
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qmodels.VectorParams(
                size=settings.embedding_dim, distance=qmodels.Distance.COSINE
            ),
        )


def upsert_chunks(points: list[tuple[str, list[float], dict[str, Any]]]) -> None:
    """points: list of (point_id, vector, payload)."""
    if not points:
        return
    settings = get_settings()
    client = get_qdrant_client()
    client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            qmodels.PointStruct(id=point_id, vector=vector, payload=payload)
            for point_id, vector, payload in points
        ],
    )


def set_current_flag(document_version_id: str, is_current: bool) -> None:
    """Flips the is_current payload flag for every point of a version, so
    dense retrieval can filter to only-current versions without a Postgres
    join. Called whenever a re-upload supersedes a version (see
    document_service.upload_document)."""
    settings = get_settings()
    client = get_qdrant_client()
    if not client.collection_exists(settings.qdrant_collection):
        return
    client.set_payload(
        collection_name=settings.qdrant_collection,
        payload={"is_current": is_current},
        points=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="document_version_id",
                    match=qmodels.MatchValue(value=document_version_id),
                )
            ]
        ),
    )


def search(
    query_vector: list[float],
    *,
    top_k: int,
    tenant_id: str,
    equipment_type: str | None = None,
    equipment_id: str | None = None,
    document_id: str | None = None,
) -> list[tuple[str, float, dict[str, Any]]]:
    """Dense search scoped to the tenant and only-current document versions.
    Returns (chunk_id, score, payload)."""
    settings = get_settings()
    client = get_qdrant_client()
    if not client.collection_exists(settings.qdrant_collection):
        return []

    must: list[qmodels.FieldCondition] = [
        qmodels.FieldCondition(key="tenant_id", match=qmodels.MatchValue(value=tenant_id)),
        qmodels.FieldCondition(key="is_current", match=qmodels.MatchValue(value=True)),
    ]
    if equipment_type:
        must.append(
            qmodels.FieldCondition(
                key="equipment_type", match=qmodels.MatchValue(value=equipment_type)
            )
        )
    if equipment_id:
        must.append(
            qmodels.FieldCondition(
                key="equipment_id", match=qmodels.MatchValue(value=equipment_id)
            )
        )
    if document_id:
        must.append(
            qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=document_id))
        )

    results = client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        query_filter=qmodels.Filter(must=must),
        limit=top_k,
        with_payload=True,
    )
    return [(str(point.id), float(point.score), point.payload or {}) for point in results.points]


def delete_by_document_version(document_version_id: str) -> None:
    settings = get_settings()
    client = get_qdrant_client()
    if not client.collection_exists(settings.qdrant_collection):
        return
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="document_version_id",
                        match=qmodels.MatchValue(value=document_version_id),
                    )
                ]
            )
        ),
    )
