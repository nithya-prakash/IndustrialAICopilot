"""Shared LLM error type.

The provider-agnostic `chat_completion` helper that used to live here (for a
non-agentic, single-shot RAG Q&A path) was removed along with its only
caller, `app.rag.generation.generate_answer` — see docs/architecture-decisions.md.
Both live generation paths (`app.rag.generation.call_model`, the diagnosis
agent's tool-calling step, and `app.vision.analyzer`, the VLM step) make
their provider calls directly, since both need request shapes (tools,
image content blocks) this helper never supported. `LLMError` remains here
as the shared exception type both raise and the diagnosis agent catches.
"""


class LLMError(Exception):
    pass
