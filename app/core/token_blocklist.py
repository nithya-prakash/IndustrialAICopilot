"""JWT revocation via a Redis blocklist keyed by token jti.

Access tokens are stateless by design (no DB round-trip needed to validate
one), so revocation needs its own store. Redis already backs Celery in
this stack (app/tasks/celery_app.py) — reusing it here avoids adding new
infrastructure. Each blocklist entry's TTL is set to the token's own
remaining time-to-live, so a revoked token's entry expires at the exact
moment the token itself would have expired anyway — no separate cleanup
job needed, and the blocklist never grows unbounded.
"""
from datetime import UTC, datetime

import redis.asyncio as redis

from app.config import get_settings

_BLOCKLIST_PREFIX = "revoked_jwt:"


def get_redis_client() -> redis.Redis:
    """Deliberately NOT cached (e.g. via lru_cache) — a redis.asyncio
    client's connection pool is bound to whatever event loop was running
    when it first actually connects. The backend serves every request off
    one persistent event loop for the process's whole lifetime, so a
    cached client would be harmless there — but the test suite creates a
    fresh event loop per test function (pytest-asyncio, function-scoped),
    and a cached client from an earlier test's now-closed loop raises
    "RuntimeError: Event loop is closed" on the next one. redis.from_url
    doesn't eagerly open a connection, so constructing fresh here has
    negligible overhead — the same class of bug already found and fixed
    for the ingestion worker's async engine (see
    app/services/ingestion_service.py), a different fix shape because
    that one rotates event loops via asyncio.run() per task rather than
    per test."""
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)


async def revoke_token(jti: str, expires_at: datetime) -> None:
    ttl_seconds = int((expires_at - datetime.now(UTC)).total_seconds())
    if ttl_seconds <= 0:
        return  # already expired — nothing left to block
    client = get_redis_client()
    await client.set(f"{_BLOCKLIST_PREFIX}{jti}", "1", ex=ttl_seconds)


async def is_token_revoked(jti: str) -> bool:
    client = get_redis_client()
    return bool(await client.exists(f"{_BLOCKLIST_PREFIX}{jti}"))
