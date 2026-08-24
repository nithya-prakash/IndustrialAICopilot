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
- [Migrations](#migrations)
- [Retrieval evaluation](#retrieval-evaluation)
- [Diagnosis agent evaluation](#diagnosis-agent-evaluation)
- [Try the document pipeline](#try-the-document-pipeline)
- [Try the sensor pipeline](#try-the-sensor-pipeline)
- [Try the diagnosis agent](#try-the-diagnosis-agent)
- [Try the approval workflow](#try-the-approval-workflow)
- [Try the frontend](#try-the-frontend)
- [Try observability](#try-observability)
- [Implementation log](#implementation-log) (full build-out, in `docs/implementation-log.md`)
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
See [Try the diagnosis agent](#try-the-diagnosis-agent) below to run this
end to end.

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

`make test` includes everything: unit tests, real-Docker-infra integration
tests (Postgres/Qdrant), and the mocked AI-pipeline tests (VLM, agent
tool-loop, full end-to-end diagnosis pipeline) — all deterministic, none
needing a paid API key. The two tests under `tests/live/` are the only
ones in the suite that make a real, billed call to an external provider;
they're marked `@pytest.mark.live` and run as part of `make test` too, but
report **SKIPPED** (not passed) unless `ANTHROPIC_API_KEY` is set — a
skipped run can never be mistaken for a verified one. Diagnosis-quality
evaluation against real API responses is separate — see "Diagnosis agent
evaluation" below.

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

## Diagnosis agent evaluation

```bash
make eval-diagnosis    # python -m evaluation.diagnosis_eval, inside the backend container
```

Runs a 5-scenario labeled set (`data/evaluation/diagnosis_scenarios.json`)
through the real diagnosis agent loop against live Postgres/Qdrant, using
the same self-seeded `evaluation` tenant as retrieval evaluation above
(manual + seeded sensor history + seeded equipment/maintenance data — all
idempotent, no manual setup). For each scenario it measures **tool
recall** (did the agent call the tools a competent diagnostician needs for
this question, against a hand-labeled expectation), **evidence-type
coverage**, **citation validity rate** (fraction of causes with real
supporting evidence — the citations themselves are already guaranteed
non-fabricated by the agent loop's own validation, Phase 6), and whether
severity met a deterministically-grounded floor where one applies (e.g.
the seeded MOTOR-001 vibration anomalies should force at least "medium").
Deliberately does **not** attempt an LLM-as-judge quality score on the
diagnosis text — see `docs/architecture-decisions.md` for why that would
be exactly the kind of unverified metric this project avoids elsewhere.

**Requires `ANTHROPIC_API_KEY`** — unlike retrieval evaluation, there's no
local stand-in for the agent's own reasoning, so with no key configured
(the case in this project's own development environment) this prints
`NOT RUN — LIVE MODEL CREDENTIALS NOT CONFIGURED` and exits, rather than
running against a fake model and presenting that as a real report; see
Known limitations.

## Try the document pipeline

```bash
docker compose run --rm backend python scripts/generate_sample_manual.py
```

generates a synthetic electric-motor manual at `data/manuals/electric_motor_manual.pdf`
(original content, not copied from any real manufacturer). Upload it:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"tech1","email":"tech1@example.com","password":"correct-horse-battery","tenant_id":"acme"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -X POST localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@data/manuals/electric_motor_manual.pdf;type=application/pdf" \
  -F "equipment_type=electric_motor" -F "equipment_id=MOTOR-001"
```

Poll `GET /api/v1/documents/{id}` — status moves through
`uploaded -> processing -> extracting -> (ocr) -> chunking -> embedding ->
indexing -> ready`, ending with real chunks in Postgres and Qdrant, each
tagged with its section/subsection (e.g. "Troubleshooting > Unusual noise"),
page number, and equipment metadata.

## Try the sensor pipeline

```bash
docker compose run --rm backend python scripts/seed_sensor_data.py acme
```

Generates synthetic hourly sensor CSVs (`data/sensors/*.csv`, 14 days) and
loads them for tenant `acme`. `motor_001` tells a deliberate story tied to
the sample manual: temperature drifts upward over the last 2 days
(developing overheating) and vibration gets 5 injected spikes crossing the
manual's stated 4.5 mm/s guidance. Then, as any user registered in `acme`:

```bash
curl "localhost:8000/api/v1/sensors/MOTOR-001/analysis?metric=temperature&start_time=2026-08-09T00:00:00Z&end_time=2026-08-23T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN"
```

returns real trend direction/slope, statistical anomalies, threshold
violations (with the manual citation attached), and baseline comparison —
all computed from the actual seeded data, not canned.

## Try the diagnosis agent

```bash
docker compose run --rm backend python scripts/seed_equipment_data.py acme
```

Seeds `Equipment` + `MaintenanceTask` rows for MOTOR-001/PUMP-001/CONVEYOR-001
(some deliberately overdue). Then:

```bash
curl -X POST localhost:8000/api/v1/copilot/query \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Why is MOTOR-001 vibrating excessively?","equipment_id":"MOTOR-001","equipment_type":"electric_motor"}'
```

drives the full pipeline: creates a conversation, runs the tool-calling
agent loop (search manuals / sensor history / maintenance schedule / image
analysis / calculator as needed), computes confidence deterministically
from what evidence was actually gathered, and returns a structured
diagnosis. Without `ANTHROPIC_API_KEY` configured this returns a `200` with
`status: "failed"` and a clear `error_message` rather than a crash — see
Known limitations.

## Try the approval workflow

```bash
# as a supervisor or admin registered in the same tenant as the diagnosis:
curl -X POST localhost:8000/api/v1/diagnoses/$DIAGNOSIS_ID/approve \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" -H "Content-Type: application/json" \
  -d '{"comments":"Confirmed via evidence review."}'
```

`GET /api/v1/diagnoses?pending_approval=true` lists diagnoses that need a
decision (completed, flagged `requires_human_approval`, not yet decided).
A decision, once made, can't be re-decided (`409` on a second attempt) —
disagreements go through a fresh question, not mutated history. Admins can
review the full audit trail: `GET /api/v1/audit-logs`.

## Try the frontend

```bash
docker compose up --build frontend
```

Open http://localhost:3002 — register (or log in), then:

- **Dashboard** — diagnosis/document/approval stats at a glance
- **Knowledge Base** — upload a manual, watch its status poll live through
  the ingestion pipeline
- **AI Copilot** — ask a question, optionally attach a component photo and
  current sensor readings, get back a structured, cited diagnosis
- **Approvals** (supervisor/admin) — approve/reject diagnoses flagged
  `requires_human_approval`
- **Audit Log** (admin) — the full compliance event trail

Role-based UI gating (nav items hidden, routes redirect) mirrors the
backend's RBAC — the frontend check is a UX courtesy, the backend
`require_roles` check is the real enforcement (see ADR). For local frontend
development with hot reload instead of the Docker build:

```bash
cd frontend && npm install && npm run dev
```

## Try observability

```bash
docker compose up --build backend prometheus grafana
```

- **Raw metrics**: http://localhost:8000/metrics (Prometheus text format —
  unauthenticated by design, see ADR)
- **Prometheus**: http://localhost:9091 — confirm the scrape target is
  `up` under Status > Targets, or run a query like `diagnoses_total`
- **Grafana**: http://localhost:3003 (login `admin`/`admin`, or browse
  anonymously — read-only viewer access is enabled for local convenience)
  → Dashboards → "Industrial Copilot", pre-provisioned with panels for
  HTTP request rate/latency, LLM/VLM call rate/latency/token usage, agent
  tool-call rate, diagnoses created, confidence distribution, and approval
  decisions

Every panel is wired to real, currently-empty-or-populated data, not a
mock — the HTTP panels populate immediately from normal API traffic; the
LLM/VLM panels show "No data" until a real Anthropic call succeeds (see
Known limitations), and the diagnosis/approval panels populate as soon as
you run the copilot/approval flows above. Confirmed end-to-end this
phase: a real `copilot/query` request (failing cleanly on the
no-API-key path) shows up in `diagnoses_total` within one scrape
interval.

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
  configured in this environment, so the actual Claude API call has never
  been exercised end-to-end here. What *is* real: agentic tool-calling
  architecture with deterministic integration tests (the full multi-turn
  tool loop, dispatch across all 7 tools, unknown-tool/malformed-argument/
  tool-exception handling, and citation validation, all driven by a
  scripted fake model — `tests/test_diagnosis_agent.py`), and a
  vision-language analysis pipeline with mocked integration coverage
  (real HTTP upload → validation → preprocessing → structured-result
  parsing → persistence, only the Anthropic SDK client mocked —
  `tests/test_vision_integration_mocked.py`), plus a full mocked
  end-to-end pipeline test spanning auth through audit logging
  (`tests/test_e2e_diagnosis_pipeline_mocked.py`). Retry/backoff for
  transient provider failures is implemented and tested
  (`app/core/retry.py`). Live-model smoke tests exist
  (`tests/live/test_live_smoke.py`, `pytest -m live`) and will run for
  real the moment `ANTHROPIC_API_KEY` is set — until then they report
  **SKIPPED**, not passed. Everything the agent depends on that doesn't
  need a paid API — retrieval, vision preprocessing, sensor analytics,
  tool dispatch, maintenance schedule computation, the approval workflow,
  audit logging — is fully live-verified against real Postgres/Qdrant
  data. Live VLM/agent accuracy verification requires provider
  credentials; no accuracy claim is made without one.
- No local VLM option (Qwen-VL/LLaVA) — the provider abstraction supports
  adding one, but it wasn't built this phase (see ADR for the trade-off).
- Tool-calling only supports `LLM_PROVIDER=anthropic` — the agent needs
  the raw Anthropic `tools=` request shape, which the (now-removed)
  provider-agnostic generation helper never supported (see ADR's Fix Pass
  entry). The vision pipeline's separate `VISION_PROVIDER` setting still
  supports both Anthropic and OpenAI.
- Prometheus/Grafana observability covers the FastAPI backend process only
  — the Celery worker (document ingestion) isn't scraped, since it runs
  multiple forked processes and doesn't serve HTTP (see ADR for what that
  would take to add).
- LLM/VLM cost tracking (`llm_cost_usd_total`) stays at zero unless you
  configure your own current provider rate — no price is hard-coded (see
  ADR). Token *counts* are always tracked from the provider's real usage
  response, cost is opt-in on top of that.
- Diagnosis-agent evaluation (`evaluation/diagnosis_eval.py`) joins the
  same no-API-key limitation as the diagnosis agent itself — the harness,
  scoring functions, and self-seeding are fully built and verified, but
  producing a real report needs a configured `ANTHROPIC_API_KEY`.
  Deliberately doesn't attempt an LLM-as-judge quality score even with a
  key available — see ADR for why that's a scoping choice, not a gap to
  fill later.
