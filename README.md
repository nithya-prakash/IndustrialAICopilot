# Industrial Multimodal AI Copilot

Evidence-based diagnostic copilot for manufacturing technicians: combines a
technician's question, a component photo, sensor readings, and technical
manuals into a structured, cited diagnosis with confidence scoring and
human-in-the-loop approval for high-risk cases.

**Status: Phase 3 (RAG) complete.** This README will grow
into a full portfolio writeup (architecture, evaluation results, screenshots)
as later phases land — see [`docs/architecture-decisions.md`](docs/architecture-decisions.md)
for design rationale on the choices below.

## Stack

- **Backend**: FastAPI, SQLAlchemy (async), Alembic, PostgreSQL
- **Ingestion**: pdfplumber (structure-aware extraction), Tesseract OCR
  fallback for scanned pages, Celery + Redis for async processing
- **Retrieval**: Qdrant (dense) + BM25 (lexical) hybrid search with
  Reciprocal Rank Fusion, cross-encoder reranking, all local models
- **AI providers**: configurable — Anthropic Claude by default, no dependency
  on a paid OpenAI key for local development (also supports Ollama/any
  OpenAI-compatible server via `LLM_BASE_URL`)
- **Infra**: Docker Compose, structured logging (structlog)

## Local setup

```bash
cp .env.example .env   # then set ANTHROPIC_API_KEY if you want live LLM calls
docker compose up --build
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

## Running tests

```bash
make test    # unit tests, run inside the backend container
```

## Migrations

```bash
make migrate              # apply migrations
make revision m="message" # generate a new migration from model changes
```

## Retrieval evaluation

```bash
make eval    # python -m evaluation.run, inside the backend container
```

Runs a 7-question ground-truth set (`data/evaluation/rag_questions.json`)
through the real hybrid retrieval pipeline against live Postgres+Qdrant and
prints/saves actual measured Recall@K, Precision@K, MRR, and nDCG@5 — no
metric here is hard-coded. Self-contained: indexes the synthetic sample
manual automatically on first run if it isn't already there. Current
measured result: **MRR 0.886, Recall@5 1.0, Recall@3 0.857** (one query — a
paraphrase, "hot to the touch" for "overheating" — ranks the correct chunk
at position 5 rather than top-3, a genuine retrieval limitation, not
smoothed over).

## Implemented so far

**Phase 1 — Foundation**
- Configuration via Pydantic Settings (`app/config.py`), no hard-coded secrets
- Async SQLAlchemy engine + session management, Alembic migrations
- Structured JSON logging with per-request context (`app/logging_config.py`)
- User model + role-based auth (technician / supervisor / admin): register,
  login, JWT bearer tokens, password hashing (bcrypt)
- Rate limiting (slowapi), CORS, security headers, request-ID propagation
- Health check endpoint with a live database check
- Dockerized backend + Postgres + Qdrant with health checks

**Phase 2 — Document Intelligence**
- `Document` / `DocumentVersion` / `DocumentChunk` models with real document
  versioning (re-upload supersedes without losing history)
- Tenant-scoped isolation (`tenant_id` on `User`/`Document`) — manuals are
  shared within a company, never leaked across tenants; covered by tests
- PDF upload with MIME + magic-byte validation, size limits, safe on-disk
  storage
- Structure-aware extraction (pdfplumber font-size heading detection) —
  chunks split on heading boundaries first, not naive fixed-size windows
- OCR fallback (Tesseract + pdf2image) for scanned pages with no text layer
- Local embeddings (sentence-transformers) + Qdrant indexing, all async via
  Celery/Redis with a live status machine the frontend can poll
- Document list/detail/delete endpoints (delete cleans up DB rows, on-disk
  files, and Qdrant points)

**Phase 3 — RAG**
- Hybrid retrieval: dense (Qdrant) + BM25 (lexical, Postgres-scoped),
  combined with Reciprocal Rank Fusion (`app/rag/retrieval.py`)
- Cross-encoder reranking (local, `sentence-transformers` `CrossEncoder`)
- Metadata filtering (tenant always enforced; equipment type/ID, document,
  current-version-only optional) — verified live, including that a
  different tenant gets zero results from another tenant's manuals
- Grounded generation (`app/rag/generation.py`) with structural citation
  validation: the model cites by index into a numbered source list, so a
  citation is either a real retrieved chunk or flagged invalid and
  dropped — never a fabricated filename/page
- Configurable LLM provider (`app/llm/client.py`): Anthropic by default,
  OpenAI-compatible (incl. local Ollama) as a drop-in alternative
- Retrieval evaluation harness with real Recall@K/Precision@K/MRR/nDCG@K
  (`evaluation/run.py`, `make eval`)

## Not yet implemented

Vision analysis (Phase 4) is next. See the phase plan in the project
brief for the full roadmap.

## Known limitations

- Structure detection is a font-size heuristic, not a layout ML model — it
  works well on manuals with consistent heading styles but can misdetect
  structure in inconsistently formatted documents. OCR'd pages have no font
  metadata at all, so heading detection there falls back to a weaker
  text-pattern heuristic (numbered/ALL-CAPS headings).
- No token revocation/blocklist yet (JWTs are valid until expiry).
- BM25 is recomputed per query over the tenant-scoped candidate set fetched
  from Postgres rather than a persistent index — fine at portfolio scale,
  documented as a scaling limitation in the ADR.
- Live end-to-end LLM calls (`app/rag/generation.py`) are implemented and
  thoroughly tested (parsing, citation validation), but have not been
  verified against a real Anthropic call in this environment — no API key
  is currently configured. Fails cleanly with a clear error rather than
  crashing.
