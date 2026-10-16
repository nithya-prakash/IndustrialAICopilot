"""Copy a Qdrant collection into a new one with a different embedding model, keeping ids/payloads.

    docker compose run --rm backend python scripts/reembed_collection.py TARGET_COLLECTION MODEL DIM

Lets retrieval be evaluated with another embedding model without re-ingesting documents: point ids
and payloads (which hold each chunk's text) are reused, only the vectors are recomputed. Then run an
evaluation against it with QDRANT_COLLECTION=TARGET_COLLECTION EMBEDDING_MODEL=MODEL
EMBEDDING_DIM=DIM.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client.http import models as qmodels  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.rag.qdrant_store import get_qdrant_client  # noqa: E402

BATCH = 64


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    target, model_name, dim = sys.argv[1], sys.argv[2], int(sys.argv[3])
    source = get_settings().qdrant_collection
    client = get_qdrant_client()
    if client.collection_exists(target):
        client.delete_collection(target)
    vectors_config = qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE)
    client.create_collection(target, vectors_config=vectors_config)
    model = SentenceTransformer(model_name)
    offset, total = None, 0
    while True:
        points, offset = client.scroll(source, limit=BATCH, offset=offset, with_payload=True)
        if not points:
            break
        vectors = model.encode(
            [p.payload["content"] for p in points], normalize_embeddings=True,
            show_progress_bar=False
        )
        client.upsert(
            target,
            points=[
                qmodels.PointStruct(id=p.id, vector=v.tolist(), payload=p.payload)
                for p, v in zip(points, vectors, strict=True)
            ],
        )
        total += len(points)
        if offset is None:
            break
    print(f"copied {total} points: {source} -> {target} with {model_name} ({dim} dims)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
