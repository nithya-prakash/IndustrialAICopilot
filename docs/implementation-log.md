# Implementation Log

What was built, area by area, plus how each was verified. See the
[project README](../README.md) for the overview, quick-start commands,
and architecture, and [`architecture-decisions.md`](architecture-decisions.md)
for the *why* behind the non-obvious choices referenced below.

## Foundation
- Configuration via Pydantic Settings (`app/config.py`), no hard-coded secrets
- Async SQLAlchemy engine + session management, Alembic migrations
- Structured JSON logging with per-request context (`app/logging_config.py`)
- User model + role-based auth (technician / supervisor / admin): register,
  login, JWT bearer tokens, password hashing (bcrypt)
- Rate limiting (slowapi, enforced per-route on auth/upload/AI endpoints —
  see "Fix Pass" below), CORS, security headers, request-ID propagation
- Health check endpoint with a live database check
- Dockerized backend + Postgres + Qdrant with health checks

## Document Intelligence
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

## RAG
- Hybrid retrieval: dense (Qdrant) + BM25 (lexical, Postgres-scoped),
  combined with Reciprocal Rank Fusion (`app/rag/retrieval.py`)
- Cross-encoder reranking (local, `sentence-transformers` `CrossEncoder`)
- Metadata filtering (tenant always enforced; equipment type/ID, document,
  current-version-only optional) — verified live, including that a
  different tenant gets zero results from another tenant's manuals
- Grounded generation with structural citation validation, now living in
  the diagnosis agent (`app/agents/diagnosis_agent.py:_validate_causes`,
  called via `app/rag/generation.py:call_model` — consolidated here in the
  Fix Pass below, see that section and the ADR): every tool call attaches
  real citation strings built from actual retrieved data, accumulated into
  a session-wide set, and the model's final citations are checked against
  it — a citation that doesn't match something actually gathered is
  dropped, never trusted
- Retrieval evaluation harness with real Recall@K/Precision@K/MRR/nDCG@K
  (`evaluation/run.py`, `make eval`)

## Vision
- Image validation via real decode (PIL), not just a trusted Content-Type
  header — rejects corrupt/non-image files
- Server-side re-encoding as a side effect that both strips EXIF metadata
  (privacy — phone photos often carry GPS) and downscales to a bounded size
- Configurable VLM provider (`app/vision/analyzer.py`): Anthropic or OpenAI,
  its own provider switch independent of the diagnosis agent's LLM call
  (which is Anthropic-only — see the ADR's Fix Pass entry on `LLM_PROVIDER`)
- Structured output (observations with confidence, explicit limitations),
  never inventing measurements/temperatures/internal-component condition —
  enforced by the prompt *and* a structural post-hoc check
  (`_flag_suspected_measurements`) that scans the model's actual output for
  measurement-like patterns rather than only trusting the instruction
- `ImageAnalysis` model, tenant-isolated, synchronous request/response
  (single VLM call, no async pipeline needed)

## Sensor Intelligence
- `SensorReading` model: narrow/long schema (one row per metric per
  timestamp), maps directly onto the `query_sensor_history(equipment_id,
  metric, start_time, end_time)` tool signature the diagnosis agent uses
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

## Diagnosis Agent
- Single Claude tool-use agent, 7 tools (`app/tools/`) — not a multi-agent
  framework (see ADR)
- `Equipment` / `MaintenanceTask` / `Conversation` / `Message` / `Diagnosis`
  models — `Equipment` deferred until this tool genuinely needed real
  per-equipment data (see ADR)
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
  real data; a failed diagnosis still retains the evidence and tool calls
  gathered before the failure (a real gap found and fixed, not assumed
  correct)

## Human Approval
- `Approval` model: one decision per diagnosis (`UniqueConstraint` on
  `diagnosis_id`) — approving/rejecting twice returns `409`, live-verified;
  disagreements go through a fresh question, not mutated history
- `POST /api/v1/diagnoses/{id}/approve` / `.../reject`, role-gated to
  supervisor/admin (`403` for technician, live-verified)
- `GET /api/v1/diagnoses?pending_approval=true` — completed, flagged
  `requires_human_approval`, not yet decided
- `AuditLog`: append-only event log covering the diagnosis lifecycle
  (created/failed/approved/rejected) and document lifecycle
  (uploaded/deleted); admin-only `GET /api/v1/audit-logs`
- Live-verified end-to-end through the real HTTP API: technician blocked,
  supervisor approves with comments, second decision attempt rejected with
  `409`, admin sees the approval event in the audit log, diagnosis drops
  out of the pending-approval list once decided

## Frontend
- React 19 + Vite + TypeScript SPA (`frontend/`), hand-rolled CSS design
  system (`src/index.css`) — no UI framework dependency (see ADR)
- Typed API client layer (`src/api/`) mirroring every backend Pydantic
  schema, JWT persisted client-side, `ApiError` surfaces real backend
  error details rather than a generic failure message
- Auth via React Context (`AuthContext`) — the one genuinely global piece
  of client state; everything else is server state fetched per-page
- Role-based UI gating (nav hidden + route-level `RequireRole` guards) for
  technician/supervisor/admin, layered on top of (not replacing) the
  backend's own RBAC enforcement — live-verified that a technician gets
  both the hidden nav item and a redirect, while the API still 403s
  independent of the UI
- Pages: Dashboard, Knowledge Base (upload + live-polling status), AI
  Copilot (question + optional image/sensor evidence), Evidence panel
  (integrated into the diagnosis view), Approval Dashboard, Diagnosis
  Detail, Audit Log, Login/Register
- Dockerized (multi-stage `node:20-alpine` build → `nginx:1.27-alpine`
  static serve), `VITE_API_BASE_URL` baked in at build time to the
  host-reachable backend URL, not the Docker-internal service name (see
  ADR)
- Live-verified in-browser across all pages/roles/flows (register, login,
  upload, query, approve, reject, navigate) with zero console errors,
  including the Dockerized build served on its own port with a real
  cross-origin request to the backend (no CORS failure, no mocked
  response)

## Observability
- Prometheus metrics (`app/observability/metrics.py`), scraped from a
  `/metrics` endpoint, deliberately unauthenticated (standard Prometheus
  practice — see ADR)
- HTTP metrics (`app/main.py`): request rate + duration, labeled by
  route *template* (`/api/v1/diagnoses/{diagnosis_id}`), not raw path —
  avoids unbounded label cardinality from UUIDs or scanned URLs
- LLM/VLM metrics (`app/llm/client.py`, `app/vision/analyzer.py`,
  `app/agents/diagnosis_agent.py`): call rate/status, latency, and real
  token counts from each provider's own `usage` field — one shared
  `record_llm_call()` helper across all three call sites (generation,
  vision, agent)
- Cost tracking is opt-in and config-driven
  (`ANTHROPIC_INPUT_COST_PER_1K_USD` etc., default `0.0`) rather than a
  hard-coded price table — this project's standing rule against
  presenting a fabricated number as real, applied to cost the same way
  it's applied to citations and measurements (see ADR)
- Agent tool-call metrics: rate/status/latency per tool
  (`app/agents/diagnosis_agent.py`), so a slow or failing tool in a
  multi-step diagnosis is visible, not just the end-to-end result
- Business metrics: `diagnoses_total` (status/severity),
  `diagnosis_confidence` (histogram), `approvals_total` (decision) —
  hooked into diagnosis creation/failure
  (`app/agents/diagnosis_agent.py`) and the single `_decide()` approval
  function (`app/services/approval_service.py`)
- Prometheus + Grafana containers (`docker-compose.yml`,
  `observability/`), Grafana pre-provisioned with a Prometheus datasource
  and a 9-panel starter dashboard — no manual setup required after
  `docker compose up`
- Scoped out, documented as such: Celery worker/ingestion metrics (would
  need a multiprocess-safe registry — see ADR)
- Incidental fix found via `docker compose ps` while verifying this area:
  the frontend container had been reporting `unhealthy` since it was
  built, despite serving correct traffic — its Dockerfile `HEALTHCHECK`
  used `wget http://localhost:3000/`, which resolves to `::1` first
  inside that image and fails, since nginx only binds IPv4. Fixed to
  check `127.0.0.1` directly (see ADR)
- Live-verified in Docker (not just unit tests): `/metrics` returns real
  data after real requests; Prometheus target shows `up` and its scraped
  values match the backend's own `/metrics` output exactly; the Grafana
  dashboard renders all 9 panels with no query errors — HTTP panels show
  real traffic immediately, LLM/agent panels correctly show "No data"
  (no fabricated placeholder values); a real `POST /copilot/query`
  request through the full HTTP stack (register → auth → agent →
  clean no-API-key failure) shows up in `diagnoses_total` end-to-end,
  from the Python counter through Prometheus's scrape to a live PromQL
  query, within one scrape interval

## Evaluation
- Diagnosis-agent evaluation harness (`evaluation/diagnosis_eval.py`,
  `make eval-diagnosis`), same self-contained/self-seeding pattern as the
  retrieval harness, extended to a surface local models can't cover: the
  agent's own tool-selection and reasoning
- 5-scenario labeled ground-truth set
  (`data/evaluation/diagnosis_scenarios.json`) written directly against
  already-verified synthetic data from earlier work (the injected
  MOTOR-001 vibration spikes, the deliberately-overdue CONVEYOR-001
  maintenance task) — no new fixtures invented for this
- Pure, unit-tested scoring functions
  (`app/evaluation/diagnosis_scoring.py`): tool recall, evidence-type
  coverage, citation validity rate, severity-floor check — all
  structural/deterministic, deliberately not an LLM-as-judge quality
  score (see ADR for why grading diagnosis prose with another
  unverified model call would undermine this project's own "never
  present a fabricated number as real" rule)
- Severity floor is only asserted where grounded in a rule the codebase
  already enforces deterministically (the diagnosis agent's
  anomaly-driven escalation) — not a subjective judgment about the
  "right" diagnosis
- Live-verified in Docker: the harness's missing-key path exits cleanly
  with a clear message rather than crashing or writing a fabricated
  report (confirmed — this environment has no `ANTHROPIC_API_KEY`, the
  same standing limitation carried throughout); separately verified
  the full pipeline's wiring end-to-end (self-seeding against real
  Postgres, real `run_diagnosis` persistence, scoring against real
  `Diagnosis` objects) using a scripted stand-in model, via a one-off
  script written and discarded specifically for this verification, not
  left in the codebase as a testing backdoor

## CI/CD
- GitHub Actions workflow (`.github/workflows/ci.yml`), three parallel
  jobs on every push/PR to `main`:
  - **backend** — ruff + pytest (same suite as local `make test`), with
    the same `tesseract-ocr`/`poppler-utils` system packages the
    Dockerfile installs, since `app/ingestion/ocr.py`'s tests exercise
    real binaries, not mocks; plus a real Qdrant service container,
    since document-deletion cleanup exercises a real `QdrantClient`
  - **frontend** — `npm run lint` + `npm run build` (tsc + vite), plus a
    `docker build` of the frontend image so a broken multi-stage
    Dockerfile fails CI, not just a future `docker compose up`
  - **compose-smoke-test** — builds the real backend image and brings up
    `backend` + `worker` against real Postgres/Qdrant/Redis through
    docker-compose's own health-check chain, then round-trips a real
    register → JWT → authenticated `/me` request — the CI equivalent of
    the manual `curl` verification this project has run by hand
    throughout
- This project had no git history for most of its build — the work
  existed only on disk, Docker-verified area by area. Reconstructed as
  one commit per build area (see ADR) using this project's own
  documentation as the record of what changed when, so CI has real
  history to run against
- Live-verified against real GitHub Actions runs after pushing: the
  first run correctly caught a genuine gap — two tests hit a real Qdrant
  client for document-deletion cleanup, and the `backend` job had no
  Qdrant service, something the local Docker-based workflow could never
  have caught since Qdrant is always running there as a sibling service.
  Fixed by adding a `services: qdrant:` block to that job (verified the
  fix directly — a standalone Qdrant + the same two test files, 8/8
  passed — before pushing again) — exactly the kind of thing CI exists
  to catch, working as intended on the very first real run

## Final Polish
- [`security.md`](security.md): a consolidated security model doc,
  fulfilling a promise an earlier ADR entry made and left unfulfilled for
  a while (caught while surveying the repo) — every claim in it cites the
  specific file/mechanism that backs it, written entirely from code that
  already existed and was already tested by this point
- `LICENSE` (MIT) added
- README restructured for a first-time reader: a "Why this exists"
  framing section, a Mermaid architecture diagram (chosen over
  screenshots — no tooling path from a captured screenshot to a
  committable image file), a collapsible table of contents, and this
  implementation log split out to keep the README itself short
- Cleaned up leftover Vite-scaffold defaults never touched since the
  frontend was first built (`frontend/package.json`'s placeholder
  name/version, `frontend/package-lock.json` resynced to match,
  `frontend/README.md` replaced — it was still the unedited Vite
  template README)
- Re-verified clean: `ruff check .` and the full test suite pass against
  the final state; `npm run build`/`npm run lint` pass on the frontend

## Fix Pass (post-audit)
Full read-only audit of the finished 12-phase MVP, followed by fixes for
every verified gap it found — see
[`architecture-decisions.md`](architecture-decisions.md)'s "Fix Pass"
section for the *why* behind each of these.
- Rate limiting actually enforced: `app/core/rate_limit.py` (shared
  `Limiter`, avoiding a circular import) plus `@limiter.limit(...)` on
  auth register/login, document upload, image analyze, and copilot query,
  each independently configurable (`RATE_LIMIT_AUTH`/`_UPLOAD`/`_AI`);
  `rate_limit_exceeded_total` metric; verified with both a real request-
  sequence test suite (`tests/test_rate_limit.py`) and a live `curl` loop
  against the running container
- Dead RAG-generation code (`app/rag/generation.py`'s index-marker citation
  parser, zero production callers) removed; the file now holds the real
  `call_model` step moved out of the diagnosis agent, so there is exactly
  one production generation/citation implementation, not two
- `tenacity`-based retry/backoff (`app/core/retry.py`) for the diagnosis
  agent's LLM call, both vision providers, and Qdrant's read + ingestion-
  write paths — transient errors only (timeouts/connection/rate-limit/5xx),
  bounded attempts, exponential backoff, logged; exhausted retries now
  raise a wrapped `LLMError`/`VisionError` (message preserved) instead of
  leaking a raw SDK exception as an unhandled 500
- Mocked VLM integration test (`tests/test_vision_integration_mocked.py`):
  real HTTP upload + validation + preprocessing + persistence, only the
  Anthropic SDK client mocked — success, malformed-response, and
  timeout-after-retries-exhausted cases
- Deterministic agent tool-loop tests extended
  (`tests/test_diagnosis_agent.py`): all 7 tools exercised through the
  loop's dispatch, unknown-tool and malformed-argument handling against the
  *real* (unmocked) executor, a tool exception that doesn't crash the loop,
  and a spy-model test proving the tool result is correctly threaded back
  into the next model call
- Full mocked end-to-end pipeline test
  (`tests/test_e2e_diagnosis_pipeline_mocked.py`): auth → tenant validation
  → real vision HTTP upload (mocked provider) → real hybrid RAG (real BM25
  + RRF + real cross-encoder rerank, only the Qdrant dense leg mocked) →
  scripted multi-turn agent tool-calling → structured diagnosis → citation
  validation → confidence/severity → the approval workflow (technician
  denied, supervisor approves) → audit record → cross-tenant isolation
- Live-model smoke test infrastructure (`tests/live/`, `pytest.mark.live`):
  real Anthropic calls for both the agent and vision paths, skipping
  cleanly (not passing, not failing) with no credentials configured
- Filename sanitization (`app/core/filenames.py`): strips path components,
  control characters, and filesystem-reserved characters from the
  *displayed* `original_filename` before storage — storage itself was
  already UUID-path-based and never exploitable, this closes the display
  side (reports, API responses, logs)
- Bounded multi-turn conversation memory: follow-up questions in an
  existing conversation now get the last 3 Q&A exchanges folded into the
  model's initial message, explicitly labeled as background rather than
  verified evidence; found and fixed a related pre-existing gap where
  conversation reuse/detail-lookup was scoped by tenant only, not by the
  user who started the thread
- Full regression check after every change: the pre-existing suite plus
  every test added this pass all pass together, run via
  `docker compose run --rm backend python -m pytest`
