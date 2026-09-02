# Industrial Multimodal AI Copilot

Evidence-based diagnostic copilot for manufacturing technicians: combines a
technician's question, a component photo, sensor readings, and technical
manuals into a structured, cited diagnosis with confidence scoring and
human-in-the-loop approval for high-risk cases.

**Status: feature-complete (Phases 1–12 of the original build plan).**
Built incrementally, phase by phase, with every phase verified live
against real Postgres/Qdrant/Docker before moving to the next — not just
unit tests. See [`docs/architecture-decisions.md`](docs/architecture-decisions.md)
for the design rationale behind every non-obvious choice below, and
[`docs/security.md`](docs/security.md) for the security model
specifically.

## Why this exists

Most "AI chatbot" portfolio projects stop at RAG. This one is built
around a harder, more realistic brief: a technician asks a question, and
the system has to *go gather real evidence* — search manuals, pull
sensor history, look at a photo, check maintenance records — before it's
allowed to say anything, and even then a low-confidence or high-severity
conclusion has to go through a human before it's actionable. That
constraint shapes almost every design decision here: citations are
structurally validated against what was actually retrieved (never
trusted from model output), confidence is computed from evidence
signals rather than self-reported by the model, and every phase's
completion was verified against real infrastructure, not asserted.

**What it demonstrates, concretely:**
- Hybrid RAG (dense + BM25 + reranking) with citations that can't be
  fabricated by construction, not just by instruction
- An agentic tool-calling loop (7 tools) with deterministic confidence
  scoring and a full test suite that exercises the control flow via a
  scripted model, independent of API availability
- Multimodal input (vision + structured sensor time-series) feeding one
  evidence pipeline
- Human-in-the-loop approval as a first-class workflow, not a bolt-on
- Production-adjacent infra: Prometheus/Grafana observability, an
  evaluation harness with real measured metrics (not asserted ones), and
  CI across backend/frontend/Docker

<details>
<summary><strong>Contents</strong></summary>

- [Architecture](#architecture)
- [Stack](#stack)
- [Local setup](#local-setup)
- [Running tests](#running-tests)
- [Usage guide](#usage-guide) — migrations, evaluation harnesses, and a
  curl-driven tour of every pipeline, in `docs/usage-guide.md`
- [Implementation log](#implementation-log) — full build-out, in
  `docs/implementation-log.md`
- [Possible next steps](#possible-next-steps)
- [Known limitations](#known-limitations)

</details>

## Architecture

```mermaid
flowchart LR
    User(["Technician / Supervisor / Admin"]) --> FE["React SPA"]
    FE -- "REST + JWT" --> API["FastAPI backend"]

    API --> PG[("PostgreSQL")]
    API --> QD[("Qdrant")]
    API -- enqueue --> RD[("Redis")]
    RD --> WK["Celery worker"]
    WK -- "extract / chunk / embed" --> PG
    WK --> QD

    API --> AG["Diagnosis agent"]
    AG -- "tool calls" --> TL["search docs · sensor history<br/>image analysis · maintenance<br/>calculator · report gen"]
    TL --> PG
    TL --> QD
    AG -- "tool-calling completion" --> LLM[["Anthropic"]]

    API -- "/metrics" --> PR["Prometheus"]
    PR --> GF["Grafana"]
```

Request flow for a diagnosis: the frontend calls `POST /copilot/query`
with a JWT; the backend hands the question to the diagnosis agent, which
decides which tools it needs (it doesn't call all seven on every
request); each tool call is scoped to the caller's own tenant and
returns real citations from Postgres/Qdrant; the agent's final answer is
validated against those citations before being persisted — anything it
claims that isn't backed by a real tool result is dropped, not shown.
See [`docs/usage-guide.md`](docs/usage-guide.md#try-the-diagnosis-agent) to
run this end to end.

## Stack

- **Backend**: FastAPI, SQLAlchemy (async), Alembic, PostgreSQL
- **Ingestion**: pdfplumber (structure-aware extraction), Tesseract OCR
  fallback for scanned pages, Celery + Redis for async processing
- **Retrieval**: Qdrant (dense) + BM25 (lexical) hybrid search with
  Reciprocal Rank Fusion, cross-encoder reranking, all local models
- **AI providers**: configurable — Anthropic Claude by default, no dependency
  on a paid OpenAI key for local development (also supports Ollama/any
  OpenAI-compatible server via `LLM_BASE_URL`)
- **Vision**: configurable VLM (Anthropic/OpenAI) for structured visual
  observations with confidence + explicit uncertainty
- **Sensor analytics**: trend detection, statistical + ML-based (Isolation
  Forest) anomaly detection, baseline comparison — `numpy`/`scikit-learn`
- **Diagnosis agent**: Claude tool-use loop over 7 tools (search manuals,
  sensor history, image analysis, maintenance schedule, safe calculator,
  report generation), deterministic confidence scoring, structural
  citation validation across all evidence types
- **Human-in-the-loop**: role-gated supervisor approve/reject workflow,
  append-only audit log
- **Frontend**: React 19 + Vite + TypeScript, hand-rolled CSS design
  system, role-aware SPA (Dashboard, Knowledge Base, AI Copilot, Evidence
  panel, Approval Dashboard, Audit Log)
- **Observability**: Prometheus metrics (HTTP, LLM/VLM calls + token usage,
  agent tool calls, diagnoses, approvals) + Grafana dashboard, on top of
  structured logging (structlog)
- **Infra**: Docker Compose

## Local setup

```bash
cp .env.example .env   # then set ANTHROPIC_API_KEY if you want live LLM calls
docker compose up --build
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

## Running tests

```bash
make test        # the full suite (mocked/deterministic — no API key needed), run inside the backend container
make test-live   # live smoke tests against a real Anthropic API — needs ANTHROPIC_API_KEY, skips cleanly without one
```

`make test` includes unit tests, real-Docker-infra integration tests
(Postgres/Qdrant), and the mocked AI-pipeline tests (VLM, agent tool-loop,
full end-to-end diagnosis pipeline) — all deterministic, none needing a
paid API key. The two tests under `tests/live/` are the only ones that
make a real, billed provider call; they run as part of `make test` too but
report **SKIPPED** (not passed) without `ANTHROPIC_API_KEY` — a skipped
run can never be mistaken for a verified one.

## Usage guide

Migrations, the retrieval/diagnosis evaluation harnesses, and a
curl-driven walkthrough of every pipeline (documents, sensors, the
diagnosis agent, approvals, the frontend, observability) live in
[`docs/usage-guide.md`](docs/usage-guide.md) — kept out of this README to
keep the overview scannable.

## Implementation log

Full build-out, area by area — what was built and how each was
verified — lives in
[`docs/implementation-log.md`](docs/implementation-log.md): Foundation,
Document Intelligence, RAG, Vision, Sensor Intelligence, Diagnosis Agent,
Human Approval, Frontend, Observability, Evaluation, CI/CD, Final Polish.

## Possible next steps

Everything in the original 12-phase build plan is complete. Genuine
extensions this project could reasonably grow into, not commitments:

- Streaming the diagnosis agent's progress to the frontend (SSE/WebSocket)
  instead of one request/response round trip, so a technician sees
  "checking sensor history…" rather than a blank wait
- Multi-turn refinement of an existing diagnosis (the `Conversation` model
  already supports follow-up messages; the agent loop doesn't yet reuse
  prior evidence when a technician asks a clarifying follow-up)
- Kubernetes manifests alongside the current Docker Compose setup, for a
  more realistic path to a multi-node deployment
- A real LLM-as-judge evaluation pass once there's an API budget to
  verify a judge model's own reliability against — deliberately not
  attempted in Phase 10 without that (see the ADR entry on why)

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
- **NOT VERIFIED — LIVE MODEL CREDENTIALS NOT CONFIGURED**: no API key is
  configured in this environment, so the actual Claude API call (agent
  reasoning, VLM accuracy, diagnosis evaluation) has never been exercised
  end-to-end here — no accuracy claim is made without one. Everything up
  to that boundary is real and live-verified, including deterministic
  integration coverage of the agent loop and a mocked VLM/end-to-end
  pipeline (see [`docs/usage-guide.md`](docs/usage-guide.md) and Running
  tests above); the live smoke tests and evaluation harness are built and
  will run for real the moment `ANTHROPIC_API_KEY` is set.
- No local VLM option (Qwen-VL/LLaVA) — the provider abstraction supports
  adding one, but it wasn't built this phase.
- Tool-calling only supports `LLM_PROVIDER=anthropic` (the agent needs the
  raw Anthropic `tools=` request shape); the vision pipeline's separate
  `VISION_PROVIDER` setting still supports both Anthropic and OpenAI.
- Prometheus/Grafana observability covers the FastAPI backend process only
  — the Celery worker (document ingestion) isn't scraped.
- LLM/VLM cost tracking (`llm_cost_usd_total`) stays at zero unless you
  configure your own current provider rate — no price is hard-coded; token
  *counts* are always tracked from the provider's real usage response.

See [`docs/architecture-decisions.md`](docs/architecture-decisions.md) for
the reasoning behind each of these.
