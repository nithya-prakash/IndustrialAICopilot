"""Optional query expansion for the dense leg of retrieval (a HyDE-style step).

A user rarely words a question the way a manual does ("the machine is shaking" versus "excessive
vibration"). With QUERY_EXPANSION=hyde the configured LLM first writes a short passage that could
appear in a technical manual and would answer the question; the dense search embeds the question
plus that passage. BM25 and the cross-encoder rerank still use the user's own words, so the
expansion can only change which candidates are found, never how they are scored.

Off by default: it adds one LLM call (about 5 s on a local 7B model) per search and, on the
evaluation sets, raised paraphrased-question MRR from 0.730 to 0.763 without changing the other
sets (docs/query-expansion.md). Any failure (no model, timeout, empty answer) falls back to the
plain query.
"""

import asyncio

from app.config import get_settings
from app.logging_config import get_logger
from app.rag.generation import call_model

logger = get_logger("query_expansion")

SYSTEM = (
    "You help search industrial maintenance and energy-efficiency documents. Given a question, "
    "write a short passage (two or three sentences) that could appear in a technical manual and "
    "would answer it. Use the specific technical terms such a manual would use. "
    "Output only the passage."
)
MAX_CHARS = 600


async def expand_query(query: str) -> str:
    """Return a hypothetical answer passage for ``query``, or "" when expansion is off or fails."""
    settings = get_settings()
    if settings.query_expansion != "hyde" or not query.strip():
        return ""
    try:
        turn = await asyncio.wait_for(
            call_model(
                [{"role": "user", "content": [{"type": "text", "text": query}]}],
                SYSTEM,
                use_tools=False,
            ),
            timeout=settings.query_expansion_timeout_seconds,
        )
    except Exception as exc:  # any failure must leave retrieval working
        logger.warning("query_expansion_failed", error=type(exc).__name__)
        return ""
    return turn.text.strip()[:MAX_CHARS]
