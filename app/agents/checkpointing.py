"""Where LangGraph keeps paused approvals.

Postgres when the app itself runs on Postgres (so a restart or a second API process does not lose a
pause), in-memory otherwise (tests, SQLite). Override with CHECKPOINT_BACKEND=memory|postgres.
A graph thread id is the diagnosis id, so a paused approval is found again from the diagnosis alone.
"""

import asyncio

from langgraph.checkpoint.memory import MemorySaver

from app.config import get_settings

_saver = None
_lock = asyncio.Lock()


async def get_checkpointer():
    global _saver
    async with _lock:
        if _saver is not None:
            return _saver
        settings = get_settings()
        use_postgres = settings.checkpoint_backend == "postgres" or (
            settings.checkpoint_backend == "auto" and settings.database_url.startswith("postgresql")
        )
        if not use_postgres:
            _saver = MemorySaver()
            return _saver

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        # LangGraph's saver talks psycopg, not asyncpg, and needs autocommit + dict rows.
        conninfo = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        pool = AsyncConnectionPool(
            conninfo,
            max_size=5,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        _saver = saver
        return _saver


async def close_checkpointer() -> None:
    global _saver
    pool = getattr(_saver, "conn", None)
    if pool is not None and hasattr(pool, "close"):
        await pool.close()
    _saver = None
