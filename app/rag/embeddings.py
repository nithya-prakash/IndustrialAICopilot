"""Local embedding model wrapper. Runs sentence-transformers on CPU by
default so RAG works with zero API keys and zero cost for local dev — the
model is swappable via EMBEDDING_MODEL/EMBEDDING_DIM without code changes.
"""
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import get_settings


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    return SentenceTransformer(settings.embedding_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = get_embedding_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()
