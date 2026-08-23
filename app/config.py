from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me-to-a-random-64-char-string"
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    database_url: str = "postgresql+asyncpg://copilot:copilot@localhost:5432/industrial_copilot"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "manual_chunks"

    anthropic_api_key: str = ""
    anthropic_agent_model: str = "claude-haiku-4-5-20251001"

    openai_api_key: str = ""

    # Configurable chat-completion provider used by RAG generation and (later)
    # the diagnosis agent. "openai" also covers Ollama/any OpenAI-compatible
    # server via LLM_BASE_URL (e.g. http://localhost:11434/v1).
    llm_provider: str = "anthropic"  # "anthropic" | "openai"
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_api_key: str = ""  # falls back to anthropic_api_key/openai_api_key if empty
    llm_base_url: str = ""

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Retrieval tuning
    dense_top_k: int = 20
    bm25_top_k: int = 20
    rrf_k: int = 60
    rerank_top_k: int = 5
    # Cross-encoder logits are unbounded (not a [0,1] probability) and their
    # range depends on the model, so this defaults low enough to be a no-op.
    # Tune based on the observed score distribution for RERANK_MODEL.
    min_relevance_score: float = -100.0

    rate_limit_default: str = "60/minute"

    redis_url: str = "redis://localhost:6379/0"

    data_dir: str = "data"
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50MB
    allowed_upload_content_types: str = "application/pdf"

    # Text below this many non-whitespace chars per page is treated as a
    # scanned page and falls back to OCR.
    ocr_page_text_threshold: int = 20
    chunk_target_chars: int = 1000
    chunk_overlap_chars: int = 150

    @property
    def allowed_upload_content_types_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_upload_content_types.split(",") if t.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def resolved_llm_api_key(self) -> str:
        if self.llm_api_key:
            return self.llm_api_key
        return self.anthropic_api_key if self.llm_provider == "anthropic" else self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
