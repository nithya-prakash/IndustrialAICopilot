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

## Phase 2

### Why `Document` / `DocumentVersion` / `DocumentChunk` as three tables, not one?
Manuals get revised. Modeling version as its own table (rather than a
version-number column on Document) means re-uploading a manual creates a
new `DocumentVersion` with `is_current=True`, flips the old version's flag
off, and keeps its chunks queryable for audit/history without deleting
anything. Retrieval by default only searches `is_current` versions — this
is the direct answer to "how do you handle document versions?"

### Why tenant-scoped isolation instead of per-user document isolation?
The brief calls for both "user-level document isolation" and a
"user/tenant" retrieval filter, which are in tension for a knowledge base:
manuals are meant to be shared across all technicians at a company, not
private per-user. Modeled as `tenant_id` on `User` and `Document` (a plain
string, no separate `Organization` table yet) — technicians at the same
company share the knowledge base; different companies never see each
other's manuals or diagnoses. This is the same boundary a real multi-tenant
industrial-AI product would need, tested explicitly (`tests/test_document_upload.py`
covers cross-tenant leakage and same-tenant sharing).

### Why heuristic (font-size) structure detection instead of a layout ML model?
A full document-layout model (e.g. LayoutLM) is a large dependency and
download for marginal benefit on the target documents (technical manuals
with consistent heading styles). Font-size clustering via pdfplumber's
per-character metadata — the most common size is body text, the largest
outlier size is a section heading, any smaller outlier is a subsection —
is fast, has zero extra model weight, and is explainable in an interview.
Documented limitation: it degrades on inconsistently formatted documents,
and OCR'd (scanned) pages have no font metadata at all, so that path falls
back to a separate regex heuristic (numbered/ALL-CAPS headings) — weaker,
and called out as such rather than pretending it's equally reliable.

### Why structure-aware chunking (heading-boundary-first) instead of naive fixed-size?
Splitting purely by character count regularly cuts a chunk mid-explanation,
which both hurts retrieval precision and makes citations misleading (a
chunk citing "page 14" that's actually half of two unrelated topics). This
pipeline flushes a new chunk at every heading boundary and only falls back
to size-based splitting within a section that runs long, carrying a small
character overlap across a within-section split so context isn't lost at
the cut. Every chunk carries its `section`/`subsection`, which is what
makes citations like "Troubleshooting > Unusual noise" possible instead of
just a page number.

### Why Celery + Redis for ingestion instead of processing uploads inline?
PDF extraction, OCR, and embedding are seconds-to-tens-of-seconds each —
doing this inline on the upload request would block the HTTP connection and
make the API unusable under any real load. Celery against Redis is the
standard, well-understood pattern for this, and the brief explicitly asks
for it. The status machine (`uploaded -> processing -> extracting -> ocr?
-> chunking -> embedding -> indexing -> ready|failed`) persisted on
`DocumentVersion` is what lets the frontend poll and show real progress
rather than a spinner with no information.

### Why store chunk text in Postgres as well as in Qdrant's payload?
Qdrant is the vector index, not the system of record — if the collection
is ever rebuilt (model change, reindex), Postgres is the source of truth
for chunk content and metadata. It also means citation validation (Phase 3)
can check a chunk against the database directly without a round-trip to
Qdrant, and sets up hybrid (BM25 + dense) retrieval without needing a
second storage system for keyword search.

