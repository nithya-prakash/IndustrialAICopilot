from functools import lru_cache
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

# The placeholder shipped in .env.example / the default below. Fine for
# local development; never acceptable once APP_ENV=production.
PLACEHOLDER_SECRET_KEY = "change-me-to-a-random-64-char-string"
MIN_PRODUCTION_SECRET_KEY_LENGTH = 32
# The local-stack defaults from docker-compose.yml / .env.example, plus a
# few obvious ones. Fine on a laptop; never in production.
KNOWN_DEFAULT_SERVICE_PASSWORDS = {
    "copilot",
    "copilot-redis",
    "postgres",
    "password",
    "admin",
    "change-me",
}
MIN_PRODUCTION_SERVICE_PASSWORD_LENGTH = 12
MIN_PRODUCTION_METRICS_TOKEN_LENGTH = 32


def _weak_url_password(url: str) -> bool:
    password = urlsplit(url).password
    return (
        not password
        or password in KNOWN_DEFAULT_SERVICE_PASSWORDS
        or len(password) < MIN_PRODUCTION_SERVICE_PASSWORD_LENGTH
    )


class InsecureConfigError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = PLACEHOLDER_SECRET_KEY
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    database_url: str = "postgresql+asyncpg://copilot:copilot@localhost:5432/industrial_copilot"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "manual_chunks"

    anthropic_api_key: str = ""
    anthropic_agent_model: str = "claude-haiku-4-5-20251001"

    anthropic_vision_model: str = "claude-haiku-4-5-20251001"

    openai_api_key: str = ""
    openai_vision_model: str = "gpt-4o-mini"
    vision_provider: str = "anthropic"  # "anthropic" | "openai"
    vision_api_key: str = ""  # falls back to anthropic_api_key/openai_api_key if empty
    # With VISION_PROVIDER=openai: any OpenAI-compatible server, e.g. a local
    # Ollama vision model (http://host.docker.internal:11434/v1 +
    # OPENAI_VISION_MODEL=qwen2.5vl:3b) — no API key or cost needed.
    vision_base_url: str = ""

    max_image_size_bytes: int = 15 * 1024 * 1024  # 15MB
    allowed_image_content_types: str = "image/jpeg,image/png,image/webp"
    # Images are downscaled before being sent to the VLM (cost/latency, and
    # most providers cap input image dimensions anyway).
    image_max_dimension_px: int = 1568

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

    confidence_approval_threshold: float = 0.75
    diagnosis_timeout_seconds: int = 5

    # Optional LLM cost tracking (USD per 1K tokens). Left at 0.0 (disabled) by
    # default rather than baking in a guessed/stale published price — set these
    # to your actual current provider rate to enable the llm_cost_usd_total
    # metric. Token *counts* are always tracked regardless (they come straight
    # from the provider's own usage response, not an estimate).
    anthropic_input_cost_per_1k_usd: float = 0.0
    anthropic_output_cost_per_1k_usd: float = 0.0
    openai_input_cost_per_1k_usd: float = 0.0
    openai_output_cost_per_1k_usd: float = 0.0

    rate_limit_default: str = "60/minute"
    # Tighter limits for security-sensitive (brute-force-able) and expensive
    # (LLM/VLM-backed) endpoints specifically — see app/core/rate_limit.py.
    rate_limit_auth: str = "10/minute"
    rate_limit_upload: str = "20/minute"
    rate_limit_ai: str = "10/minute"

    # Bounded retry/backoff for transient LLM/VLM/Qdrant failures — see
    # app/core/retry.py. Never retries validation/auth/malformed-request
    # errors, only timeouts/connection errors/rate limits/5xx.
    retry_max_attempts: int = 3
    retry_wait_min_seconds: float = 1.0
    retry_wait_max_seconds: float = 8.0

    redis_url: str = "redis://localhost:6379/0"

    # Bearer token required on GET /metrics when set (Prometheus sends it via
    # its scrape config). Empty = open, the local-stack default; required
    # when APP_ENV=production. See docs/security.md.
    metrics_token: str = ""

    data_dir: str = "data"
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50MB
    allowed_upload_content_types: str = "application/pdf"

    # Text below this many non-whitespace chars per page is treated as a
    # scanned page and falls back to OCR.
    ocr_page_text_threshold: int = 20
    chunk_target_chars: int = 1000
    chunk_overlap_chars: int = 150

    def check_production_safety(self) -> None:
        """Refuse to start in production with any of the local-demo
        credentials. The SECRET_KEY placeholder is public (it's in
        .env.example on GitHub), so anyone could forge an admin token for any
        tenant; the Postgres/Redis passwords are the docker-compose defaults;
        and without METRICS_TOKEN, /metrics is open to whoever can reach it.

        A plain RuntimeError on purpose, not a pydantic validator: a
        ValidationError's message includes the full settings input, which
        would print the API keys and database password into the startup log.
        Problems are reported by setting name only, never by value."""
        if not self.is_production:
            return
        problems = []
        if (
            self.secret_key == PLACEHOLDER_SECRET_KEY
            or len(self.secret_key) < MIN_PRODUCTION_SECRET_KEY_LENGTH
        ):
            problems.append(
                f"SECRET_KEY must be a random value of at least "
                f"{MIN_PRODUCTION_SECRET_KEY_LENGTH} characters "
                '(e.g. python -c "import secrets; print(secrets.token_urlsafe(64))")'
            )
        if _weak_url_password(self.database_url):
            problems.append(
                "DATABASE_URL must carry a non-default database password of at least "
                f"{MIN_PRODUCTION_SERVICE_PASSWORD_LENGTH} characters"
            )
        if _weak_url_password(self.redis_url):
            problems.append(
                "REDIS_URL must carry a non-default Redis password of at least "
                f"{MIN_PRODUCTION_SERVICE_PASSWORD_LENGTH} characters"
            )
        if len(self.metrics_token) < MIN_PRODUCTION_METRICS_TOKEN_LENGTH:
            problems.append(
                f"METRICS_TOKEN must be set (at least {MIN_PRODUCTION_METRICS_TOKEN_LENGTH} "
                "characters) so /metrics isn't open"
            )
        if problems:
            raise InsecureConfigError(
                "Refusing to start with APP_ENV=production: " + "; ".join(problems)
            )

    @property
    def allowed_upload_content_types_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_upload_content_types.split(",") if t.strip()]

    @property
    def allowed_image_content_types_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_image_content_types.split(",") if t.strip()]

    @property
    def resolved_vision_api_key(self) -> str:
        if self.vision_api_key:
            return self.vision_api_key
        if self.vision_provider == "anthropic":
            return self.anthropic_api_key
        return self.openai_api_key

    @property
    def vision_model(self) -> str:
        if self.vision_provider == "anthropic":
            return self.anthropic_vision_model
        return self.openai_vision_model

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
    settings = Settings()
    settings.check_production_safety()
    return settings
