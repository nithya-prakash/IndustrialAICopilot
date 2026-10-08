"""Where LangGraph keeps paused approvals.

Postgres when the database the request is actually using is Postgres (so a restart or a second API
process does not lose a pause), in-memory otherwise (tests on SQLite). The choice follows the live
session, not the DATABASE_URL setting, which can point somewhere unreachable in tests.
Override with CHECKPOINT_BACKEND=memory|postgres (postgres then uses DATABASE_URL).
A graph thread id is the diagnosis id, so a paused approval is found again from the diagnosis alone.
"""

import asyncio

from langgraph.checkpoint.memory import MemorySaver

from app.config import get_settings

_savers: dict[str, object] = {}
_lock = asyncio.Lock()


def _target(db, settings) -> str | None:
    """Connection URL for a Postgres checkpointer, or None for the in-memory one."""
    if settings.checkpoint_backend == "memory":
        return None
    if settings.checkpoint_backend == "postgres":
        return settings.database_url
    engine = db.get_bind() if db is not None else None
    if engine is not None and engine.dialect.name == "postgresql":
        return engine.url.render_as_string(hide_password=False)
    return None


async def get_checkpointer(db=None):
    settings = get_settings()
    url = _target(db, settings)
    key = url or "memory"
    async with _lock:
        if key in _savers:
            return _savers[key]
        if url is None:
            _savers[key] = MemorySaver()
            return _savers[key]

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        # LangGraph's saver talks psycopg, not asyncpg, and needs autocommit + dict rows.
        conninfo = url.replace("postgresql+asyncpg://", "postgresql://")
        pool = AsyncConnectionPool(
            conninfo,
            max_size=5,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        _savers[key] = saver
        return saver


async def close_checkpointers() -> None:
    for saver in _savers.values():
        pool = getattr(saver, "conn", None)
        if pool is not None and hasattr(pool, "close"):
            await pool.close()
    _savers.clear()
