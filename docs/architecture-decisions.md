# Architecture Decision Records

Short, interview-ready rationale for the non-obvious choices in this
project. Each entry: the decision, the alternatives considered, and why.

## Phase 1

### Why FastAPI?
Async-native (matters once the diagnosis agent is making concurrent
LLM/tool calls), Pydantic-based request/response validation gives free
OpenAPI docs and structured-output enforcement, and it's the de facto
standard for Python AI-service backends — directly relevant to the target
roles.

### Why PostgreSQL?
Relational integrity matters here: diagnoses reference documents, evidence
references chunks, approvals reference diagnoses — foreign keys and
transactions are the right tool, not a document store. JSONB columns (used
later for structured diagnosis payloads) give schema flexibility where
needed without giving up relational guarantees elsewhere.

### Why JWT bearer auth over session cookies?
Stateless, works identically for the API whether the caller is the React
frontend or a future mobile/CLI client, and needs no server-side session
store. Trade-off: revocation requires a token blocklist (not yet built) —
acceptable for a portfolio project, called out here as a known gap.

### Why configurable LLM/vision providers (not a single hard-coded API)?
The brief explicitly requires local development without a paid API key.
Anthropic Claude is the default (this developer's available key), but the
settings-driven provider switch (`VISION_PROVIDER`, future `LLM_PROVIDER`)
means the same code path works with OpenAI or a local model without a
rewrite — relevant for demonstrating vendor-agnostic AI engineering, not
just "I called the Claude API."

