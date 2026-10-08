"""Memory of past incidents: earlier diagnoses a supervisor APPROVED, found by meaning.

Only human-confirmed diagnoses are remembered, so a model's earlier mistake can't feed
back into later diagnoses. Retrieval embeds the (at most MAX_CANDIDATES most recent)
approved diagnoses of the caller's own tenant and ranks them by cosine similarity to the
query, with a small bonus for the same equipment. That is fine for hundreds of incidents;
a larger history would need a persistent vector index.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval, ApprovalDecision
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.rag.embeddings import embed_texts

MAX_CANDIDATES = 200
MIN_SIMILARITY = 0.30
SAME_EQUIPMENT_BONUS = 0.10


@dataclass
class PastIncident:
    diagnosis_id: uuid.UUID
    equipment_id: str | None
    date: str
    question: str
    summary: str
    top_causes: list[str]
    recommended_action: str
    similarity: float


def _incident_text(d: Diagnosis) -> str:
    causes = "; ".join(c.get("cause", "") for c in (d.possible_causes or [])[:3])
    return f"{d.question}. {d.summary or ''}. {causes}"


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # vectors are L2-normalised


async def search_past_incidents(
    db: AsyncSession,
    *,
    tenant_id: str,
    query: str,
    equipment_id: str | None = None,
    limit: int = 3,
    embed: Callable[[list[str]], list[list[float]]] = embed_texts,
) -> list[PastIncident]:
    rows = await db.execute(
        select(Diagnosis)
        .join(Approval, Approval.diagnosis_id == Diagnosis.id)
        .where(
            Diagnosis.tenant_id == tenant_id,
            Diagnosis.status == DiagnosisStatus.completed,
            Approval.decision == ApprovalDecision.approved,
        )
        .order_by(Diagnosis.created_at.desc())
        .limit(MAX_CANDIDATES)
    )
    diagnoses = list(rows.scalars().all())
    if not diagnoses or not query.strip():
        return []

    vectors = embed([query, *[_incident_text(d) for d in diagnoses]])
    query_vec, incident_vecs = vectors[0], vectors[1:]
    scored = []
    for d, vec in zip(diagnoses, incident_vecs, strict=True):
        similarity = _dot(query_vec, vec)
        if similarity < MIN_SIMILARITY:
            continue
        if equipment_id and d.equipment_id == equipment_id:
            similarity += SAME_EQUIPMENT_BONUS
        scored.append((similarity, d))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [
        PastIncident(
            diagnosis_id=d.id,
            equipment_id=d.equipment_id,
            date=d.created_at.date().isoformat() if d.created_at else "unknown",
            question=d.question,
            summary=d.summary or "",
            top_causes=[c.get("cause", "") for c in (d.possible_causes or [])[:3]],
            recommended_action=d.recommended_action or "",
            similarity=round(similarity, 3),
        )
        for similarity, d in scored[:limit]
    ]
