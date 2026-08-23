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

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
