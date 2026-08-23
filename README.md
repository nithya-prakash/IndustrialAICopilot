# Industrial Multimodal AI Copilot

Evidence-based diagnostic copilot for manufacturing technicians: combines a
technician's question, a component photo, sensor readings, and technical
manuals into a structured, cited diagnosis with confidence scoring and
human-in-the-loop approval for high-risk cases.

**Status: Phase 6 (Diagnosis Agent) complete.** This README will grow
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
- **Vision**: configurable VLM (Anthropic/OpenAI) for structured visual
  observations with confidence + explicit uncertainty
- **Sensor analytics**: trend detection, statistical + ML-based (Isolation
  Forest) anomaly detection, baseline comparison — `numpy`/`scikit-learn`
- **Diagnosis agent**: Claude tool-use loop over 7 tools (search manuals,
  sensor history, image analysis, maintenance schedule, safe calculator,
  report generation), deterministic confidence scoring, structural
  citation validation across all evidence types
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

**Phase 4 — Vision**
- Image validation via real decode (PIL), not just a trusted Content-Type
  header — rejects corrupt/non-image files
- Server-side re-encoding as a side effect that both strips EXIF metadata
  (privacy — phone photos often carry GPS) and downscales to a bounded size
- Configurable VLM provider (`app/vision/analyzer.py`): Anthropic or OpenAI,
  same provider-abstraction pattern as `app/llm/client.py`
- Structured output (observations with confidence, explicit limitations),
  never inventing measurements/temperatures/internal-component condition —
  enforced by the prompt *and* a structural post-hoc check
  (`_flag_suspected_measurements`) that scans the model's actual output for
  measurement-like patterns rather than only trusting the instruction
- `ImageAnalysis` model, tenant-isolated, synchronous request/response
  (single VLM call, no async pipeline needed)

**Phase 5 — Sensor Intelligence**
- `SensorReading` model: narrow/long schema (one row per metric per
  timestamp), maps directly onto the `query_sensor_history(equipment_id,
  metric, start_time, end_time)` tool signature the diagnosis agent
  (Phase 6) will use
- Snapshot ingestion (`POST /api/v1/sensors/upload`, JSON — matches the
  brief's real product flow) and historical CSV bulk-load via a seed
  script (`scripts/seed_sensor_data.py`)
- Analytics (`app/analytics/sensors.py`): trend detection (linear
  regression, reports "stable" rather than a direction when R² is too low
  to support one), statistical (z-score) anomaly detection as the default
  for explainability, Isolation Forest as an opt-in ML-based alternative,
  moving averages, baseline comparison against an equipment's own history
- Threshold checking against the one number the project's own synthetic
  manual actually states (vibration_rms > 4.5 mm/s) — no fabricated limits
  for metrics the manual doesn't address
- Live-verified against real seeded data: correctly detected the injected
  temperature drift as an "increasing" trend, flagged the elevated
  readings as statistical anomalies, caught all 5 injected vibration
  spikes via both detection methods, and confirmed tenant isolation

**Phase 6 — Diagnosis Agent**
- Single Claude tool-use agent, 7 tools (`app/tools/`) — not a multi-agent
  framework (see ADR)
- `Equipment` / `MaintenanceTask` / `Conversation` / `Message` / `Diagnosis`
  models — `Equipment` deferred since Phase 2 until this tool genuinely
  needed real per-equipment data (see ADR)
- Deterministic, rule-based confidence (`app/agents/confidence.py`) — never
  the model's self-reported number; live-verified to score <0.5 with no
  evidence and >0.5 once real evidence is gathered
- Citation validation extended to all evidence types (documents, sensor
  findings, image observations, maintenance records), not just documents —
  a cited string not matching real gathered evidence is dropped and
  flagged, never trusted
- Severity escalation floor: objective sensor anomaly evidence overrides a
  model claim of "low" severity to at least "medium"
- Safe arithmetic `calculate` tool — AST-restricted, not `eval()`
- The model-call step is injectable specifically so the loop's control
  flow (tool dispatch, citation validation, confidence/severity, failure
  handling, persistence) has real test coverage
  (`tests/test_diagnosis_agent.py`) despite no API key being available
- Live-verified against real Postgres/Qdrant/seeded data: full HTTP
  request → auth → orchestrator → clean-failure path; multi-tool
  orchestration (search + sensor history + maintenance schedule) against
  real Phase 2/3/5 data; a failed diagnosis still retains the evidence and
  tool calls gathered before the failure (a real gap found and fixed this
  phase, not assumed correct)

## Not yet implemented

Human-in-the-loop approval (Phase 7) is next. See the phase plan in the
project brief for the full roadmap.

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
- Live end-to-end LLM/VLM/agent calls (`app/rag/generation.py`,
  `app/vision/analyzer.py`, `app/agents/diagnosis_agent.py`) are
  implemented and thoroughly tested (parsing, citation validation,
  measurement-flagging, the full multi-turn tool loop via a scripted fake
  model), but have not been verified against a real Anthropic call in this
  environment — no API key is currently configured. All fail cleanly with
  a clear error rather than crashing, and that failure path is
  live-verified end-to-end through the real HTTP layer.
- No local VLM option (Qwen-VL/LLaVA) — the provider abstraction supports
  adding one, but it wasn't built this phase (see ADR for the trade-off).
- Tool-calling only supports `LLM_PROVIDER=anthropic` (plain generation in
  Phase 3 supports OpenAI-compatible too) — a scoped trade-off, not an
  oversight (see ADR).
