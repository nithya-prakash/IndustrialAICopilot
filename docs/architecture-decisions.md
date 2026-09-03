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

## Phase 3

### Why hybrid (dense + BM25) retrieval instead of dense-only?
Dense embeddings are strong on semantic similarity but weak on exact terms
that matter a lot in technical manuals — part numbers, error codes, specific
component names. BM25 catches those lexical matches dense search can miss;
dense catches paraphrases BM25 can miss ("motor won't stop shaking" vs.
"excessive vibration"). Running both and fusing beats either alone on this
kind of mixed natural-language + technical-vocabulary query.

### Why BM25 recomputed on demand instead of a persistent keyword index?
At this project's scale (hundreds of chunks per tenant), fetching the
tenant-scoped candidate set from Postgres and building an in-memory
`BM25Okapi` index per query is sub-millisecond and needs zero extra
infrastructure. The honest trade-off: this does not scale to a large corpus
the way a dedicated search engine (Elasticsearch/OpenSearch) or a
persistent index would — documented explicitly rather than silently
assumed, since a portfolio reviewer will ask "does this scale?"

### Why Reciprocal Rank Fusion instead of a weighted score combination?
Cosine similarity (bounded [0,1]) and BM25 (unbounded, corpus-dependent)
aren't on comparable scales, so averaging or weighting the raw scores would
need per-corpus calibration. RRF only uses rank position, sidesteps score
normalization entirely, and is a standard, well-understood technique — no
tuning required to get a reasonable fusion.

### Why a cross-encoder reranker (local model) instead of no reranking, or a hosted reranking API?
Bi-encoder cosine similarity and BM25 are both "generate a candidate set
cheaply" tools — the reranker's cross-encoder jointly attends over
(query, chunk) pairs, which is measurably more accurate for the final
top-k, and is the standard reason hybrid pipelines add a rerank stage
rather than serving fused results directly. Running it locally
(`sentence-transformers` `CrossEncoder`) keeps the "no paid API required
for local dev" constraint intact — a hosted reranker (e.g. Cohere Rerank)
would be a one-line swap if a project needed the accuracy/latency
trade-off it offers.

### How citations are prevented from being fabricated
The LLM is given a *numbered* list of retrieved excerpts and instructed to
cite by index (`[1]`, `[2]`), not to reproduce citation text itself. Every
`[N]` marker in the model's output is checked against the actual number of
retrieved sources: in range -> resolved to that chunk's real
filename/section/page (`RetrievedChunk.citation`, built from the database,
never from the model) — this made fabricated citations structurally close
to impossible rather than something caught by a post-hoc string match
against known document names.

**Superseded by the Phase 6 agent** (see the fix-pass audit entry below):
the diagnosis agent's tool-calling design generates citations differently —
each tool call attaches real citation strings to its result (built from
actual DB/analytics data — see `app/tools/executor.py`), the loop
accumulates every citation actually returned across all tool calls into a
session-wide `set[str]`, and the model's final `supporting_citations` are
checked against that set (`app/agents/diagnosis_agent.py:_validate_causes`)
— any citation the model states that doesn't match a real gathered result
is dropped, not trusted. Same principle (verify against what was actually
retrieved, don't trust a string match), different mechanism (set
membership against real tool results, not index-into-a-numbered-list) —
required because the agent's evidence spans four types (documents,
sensors, images, maintenance records), not just document chunks, and
citations are gathered incrementally across a multi-turn tool loop rather
than handed to the model as one fixed numbered list up front. The
now-superseded `[1]`/`[2]`-marker implementation in `app/rag/generation.py`
had zero production callers by this point and was removed as dead code
during the fix pass (see the audit entry below); `app/rag/generation.py`
now holds the live `call_model` step instead.

### How prompt injection from a malicious/compromised manual is defended against
Retrieved chunk content is untrusted data — the system prompt explicitly
states this and instructs the model to treat any instruction-like text
inside an excerpt (e.g. "ignore previous instructions") as quoted content,
not a command. This is a prompt-level defense (documented as such, not
claimed as a guarantee); `docs/security.md` covers this as a layered
concern once the agent (Phase 6) adds tool-calling, where injected content
could otherwise try to trigger unintended tool calls.

### Why configurable LLM_PROVIDER (Anthropic default, OpenAI-compatible fallback) reused from generation into the future agent?
Same rationale as the vision provider in Phase 1: local development must
not require a paid key. At the time this was written, `LLM_PROVIDER=openai`
with `LLM_BASE_URL` pointed at a local Ollama server was a one-line config
change to run entirely without any API key, via the provider-agnostic
`chat_completion` helper in `app/llm/client.py`.

**Correction (fix pass, see the entry below)**: that helper was
plain-text-only and had no tool-calling support, so when Phase 6 built the
actual agent it could not use it — the agent needs the raw Anthropic
`tools=` request shape, so `call_model` (`app/rag/generation.py`) talks to
the Anthropic SDK directly and explicitly rejects any `LLM_PROVIDER` other
than `"anthropic"`. `chat_completion`'s only caller (the now-removed
`generate_answer`) was deleted as dead code, and the function went with it.
`LLM_PROVIDER=openai`/local-Ollama is therefore **not currently a working
path for the diagnosis agent** — this is a known, documented limitation,
not a hidden one. The vision pipeline's own `VISION_PROVIDER` setting is
separate and does still support both Anthropic and OpenAI.

## Phase 4

### Why re-encode every uploaded image server-side instead of trusting/passing through the original bytes?
Three independent reasons converge on the same fix: (1) security — a
client-supplied `Content-Type` header is a claim, not a guarantee; decoding
the file with PIL (`Image.open().load()`) is what actually proves it's a
real image, not just a file with a matching extension. (2) privacy — a
technician's phone photo commonly carries EXIF GPS coordinates; re-encoding
to a fresh JPEG buffer does not copy EXIF, so it's stripped as a side
effect of the same step that does validation, not a separate policy to
remember. (3) cost/latency — downscaling to a bounded max dimension before
sending to the VLM keeps request size and API cost predictable regardless
of what a phone camera produces natively.

### Why is image analysis synchronous (request/response) instead of async via Celery like document ingestion?
Document ingestion is a multi-stage pipeline (extract → OCR → chunk →
embed → index) that can run tens of seconds on a large PDF — blocking an
HTTP request for that is a bad experience, so it's queued. A single VLM
call is one round trip; wrapping it in the same async infrastructure would
add a polling step for no real benefit at this scale. If vision latency
becomes a problem under load, this is the one function
(`app/services/image_service.py:analyze_uploaded_image`) that would move
to a Celery task — the interface wouldn't need to change.

### How fabricated measurements/temperatures/internal-damage claims are prevented, beyond the prompt
The system prompt instructs the model not to state measurements or claim
knowledge of internal/hidden condition — but a prompt instruction is not a
guarantee, so it isn't the only safeguard. `_flag_suspected_measurements`
(`app/vision/analyzer.py`) is a structural, tested check: it scans every
observation the model actually returned for a number-with-unit pattern
(mm, °C, psi, RPM, etc.) and — if the model stated one anyway — appends an
explicit limitation surfacing that fact, rather than silently trusting the
prompt worked. This mirrors the citation-validation approach in Phase 3:
don't just instruct the model and hope, add a check on the output.

### Why no local VLM (Qwen-VL/LLaVA) option, unlike the local embedding/reranking models?
The brief calls this out as "where practical." A local VLM needs a
multi-gigabyte model download and a GPU-friendly inference setup to be
usable at reasonable latency — a materially bigger lift than the embedding/
reranker models (tens of MB, fast on CPU) already running locally. The
provider abstraction (`VISION_PROVIDER`) is built so adding one later is a
new branch in `app/vision/analyzer.py`, not a rewrite — documented here as
a deliberate scope cut, not an oversight.

## Phase 5

### Why a narrow/long `SensorReading` schema (one row per metric per timestamp) instead of one wide row per snapshot?
The brief's tool signature is `query_sensor_history(equipment_id, metric,
start_time, end_time)` — that maps directly onto `WHERE metric = ? AND
recorded_at BETWEEN ? AND ?` in a narrow schema, with no per-metric column
to add every time a new sensor type shows up. The cost is one extra JOIN-free
row per metric per snapshot, which is irrelevant at this scale and normal
practice for time-series data (this is exactly what a real time-series
database like InfluxDB/TimescaleDB would model too).

### Why no `Equipment` master-data table yet, despite section 20 listing one?
`equipment_id`/`equipment_type` stayed plain indexed strings (matching the
pattern already used on `Document` and `ImageAnalysis` since Phase 2)
rather than introducing a referential `Equipment` table this phase. Two
reasons: retrofitting Phase 2/4 tables to a new FK would be churn with no
functional benefit yet, and — more importantly — a real `Equipment` table
implies real per-equipment specs (normal operating ranges, install date,
maintenance intervals), and fabricating those would be worse than not
having the table. Baseline/threshold logic here instead either (a) derives
"normal" statistically from the equipment's own historical readings
(`compare_to_baseline`), or (b) uses the one number the project's own
synthetic manual actually states (vibration_rms > 4.5mm/s). `Equipment`
becomes worth adding when Phase 6's `get_maintenance_schedule` tool needs
real schedule data to reference — deferred there, not skipped.

### Why statistical (z-score) anomaly detection by default, with Isolation Forest as an explicit opt-in?
The brief explicitly suggests "ML-based anomaly detection where
appropriate." Both are implemented (`app/analytics/sensors.py`), but
z-score is the default because a maintenance technician needs to act on
*why* something was flagged — "3.7 standard deviations above this
equipment's recent mean" is actionable and checkable; an Isolation Forest
anomaly score is not, without more explanation. Live-tested against the
synthetic motor data: both correctly catch all 5 injected vibration
spikes, but Isolation Forest additionally flags several borderline
low-vibration points a human wouldn't call anomalous — a genuine,
observed trade-off (broader multivariate sensitivity vs. explainability),
not just a theoretical one, which is exactly why both are offered rather
than picking one.

### Why is historical CSV bulk-loading a script, not a public upload API?
The brief's example data (`data/sensors/motor_001.csv`) is fixture/demo
data. In a real deployment, historical sensor data would come from a
SCADA/historian system integration, not a technician manually uploading a
CSV — building a public bulk-upload endpoint for a data path that
shouldn't exist in production would be effort spent on the wrong
abstraction. `POST /api/v1/sensors/upload` (JSON, one snapshot) matches
the brief's actual example and the real product flow: a technician
submitting current readings alongside a diagnosis question.

## Phase 6

### Why one agent with seven tools, not a multi-agent framework?
The brief explicitly warns against "fake multi-agent complexity," and
there's no task decomposition here that actually benefits from separate
agents with separate contexts — a single Claude tool-use loop deciding
which of seven tools to call, in what order, is the right level of
architecture for "gather evidence, then synthesize a diagnosis." A
framework (LangGraph, CrewAI, etc.) would add indirection without solving
a problem this project actually has; see also the Phase 1 note on why not
LangChain everywhere.

### Why confidence is computed by a rule-based formula, not the model's self-report?
LLMs are well known to be poorly calibrated at self-assessing certainty —
a model will confidently say "0.9" about a guess built on zero evidence
just as readily as about a well-supported conclusion. `app/agents/
confidence.py` instead scores concrete, auditable signals: which evidence
types were actually gathered, how many causes ended up with a real
citation, whether any tool call failed. The system prompt explicitly tells
the model not to report a confidence number at all — it's not "the model's
number, double-checked," it's a value the model never provides in the
first place. This is the direct mechanism behind "never present a
low-confidence diagnosis as certain": confidence isn't asked for, it's
calculated, live-verified to score low (<0.5) when no tools are called and
meaningfully higher once real evidence is gathered.

### How citation validation was extended from Phase 3 (documents only) to all four evidence types
Phase 3 validated citation markers against retrieved document chunks. Here,
every tool that returns citable evidence (documents, sensor findings,
image observations, maintenance records) attaches a real citation string
built from actual data — never invented by the model. The orchestrator
accumulates these into a session-wide set as tools are called, and the
final diagnosis JSON's `supporting_citations` are checked against that set
directly: a citation the model wrote that doesn't match anything actually
retrieved is dropped and flagged in `limitations`, not trusted. Same
underlying principle as Phase 3 (verify against what was actually
retrieved, not the model's claim), generalized from one evidence type to
four.

### Why the model-call step is factored out of the loop (an injectable `model_call` parameter)
No ANTHROPIC_API_KEY is configured in this environment (carried over from
Phase 3), which meant the actual multi-turn tool-calling loop — dispatch,
citation validation, confidence scoring, persistence, failure handling —
could not be exercised by a real API call this session. Separating "what
does the model say" from "what do we do about it" meant that logic could
still be thoroughly tested with a scripted fake model
(`tests/test_diagnosis_agent.py`) rather than left unverified. When a key
is available, only `_call_anthropic` needs checking — the loop control
flow already has real test coverage.

### Why only Anthropic is supported for tool-calling (unlike plain generation, which also supports OpenAI-compatible)
Anthropic and OpenAI's tool/function-calling wire formats differ enough
that supporting both properly for a multi-turn loop is real, separate work
— and without an API key for either provider, building an OpenAI path here
would be adding code with zero verification, not a shortcut. `LLM_PROVIDER=
openai` raises a clear, immediate error in the agent path rather than
silently behaving incorrectly. Documented as a scoped trade-off, not an
oversight — plain generation (Phase 3) still supports both.

### Why get_maintenance_schedule finally triggered adding the Equipment table (deferred since Phase 2)
Every prior phase's `equipment_id`/`equipment_type` stayed plain indexed
strings because nothing needed real per-equipment data — a lookup table
with no real data behind it would have been premature structure. This
tool needs actual maintenance intervals and last-performed dates to
compute overdue status, which is real per-equipment data with no honest
way to derive it from existing tables. That's the concrete trigger the
earlier ADR entries said to wait for.

## Phase 7

### Why human approval, at all?
The system computes confidence and severity itself (Phase 6), but a
computed number is not the same as a decision with consequences — an AI
diagnosis recommending equipment be taken offline, or one with confidence
below the threshold, needs a person accountable for the next action, not
just a stored score. This is the standard pattern for AI in safety- or
cost-sensitive operational contexts: the model proposes, a qualified human
disposes. `requires_human_approval` (computed deterministically in Phase 6)
is the trigger; this phase is what a supervisor actually does about it.

### Why one decision per diagnosis (a `UniqueConstraint` on `diagnosis_id`), not a mutable/re-decidable approval?
An approval is a compliance record — allowing a supervisor to silently
overwrite an earlier "approved" with "rejected" (or vice versa) would make
the audit trail lie about what was actually decided and when. If a
technician disagrees with a rejection, the honest path is a new question
(a new `Diagnosis`, evaluated fresh), not mutating history. Enforced at
the database level, not just application logic — `approve_diagnosis`/
`reject_diagnosis` both go through the same `_decide` function and a
second call for the same diagnosis gets a `409`, live-verified.

### Why structured, role-gated approve/reject rather than a generic "update diagnosis status" endpoint?
`require_roles(UserRole.supervisor, UserRole.admin)` on both endpoints
means the authorization rule is enforced once, declaratively, at the route
— not re-checked ad hoc inside a generic handler that could also do other
things. A technician being unable to approve their own diagnosis is a
real segregation-of-duties requirement for a compliance-sensitive
workflow, not an incidental restriction; live-verified as a `403`.

### Why an `AuditLog` table separate from `Diagnosis.tool_calls`?
`Diagnosis.tool_calls` (Phase 6) is a per-diagnosis, denormalized record
of what the agent did — useful for showing "how did it reach this
conclusion" on one diagnosis. `AuditLog` is the broader, append-only
compliance log the brief's section 18 asks for: who did what, when, across
diagnosis creation, approval decisions, and document lifecycle events —
queryable independent of any single diagnosis (e.g. "show me every action
this user took," not built yet, but the schema supports it directly).
Scoped this phase to the compliance-sensitive actions (diagnosis
create/approve/reject, document upload/delete) via one `log_event` call
each, rather than instrumenting every mutating endpoint — extending
coverage is the same call, not new architecture, documented as a scope
limit rather than assumed complete.

### Why `AuditLog.detail` doesn't include a full snapshot of the resource
Storing the diagnosis's full evidence/causes/etc. on every audit event
would duplicate `Diagnosis` itself and go stale the moment the source
record changed (it can't, here, but the pattern would still be wrong to
establish). `detail` holds only what's specific to *that event*
(confidence/severity at creation time, decision comments) — the audit log
points at the resource by ID and lets the caller join to the current
record for the rest, which is also why it stayed a lightweight `resource_
type`/`resource_id` pair rather than per-resource-type foreign keys.

## Phase 8

### Why hand-rolled CSS (custom properties + utility classes) instead of Tailwind or a component library (MUI, Chakra, etc.)?
A UI framework would be faster to assemble but hides the actual CSS from
an interviewer skimming the repo, and this project's differentiator is the
backend/AI engineering, not frontend polish. A small design-system file
(`src/index.css`: color/spacing/radius tokens as CSS variables, a handful
of reusable classes — `.card`, `.btn`, `.badge`, `.field`) gets a
consistent, professional look with zero dependencies and full visibility
into every rule, which matters more here than component-library velocity.

### Why React Context for auth state instead of Redux/Zustand?
The frontend has exactly one piece of genuinely global state — the
logged-in user and their token — everything else (documents, diagnoses,
approvals) is server state fetched per-page with plain `useState`/
`useEffect`, not client state that needs a store. A single `AuthContext`
(`src/context/AuthContext.tsx`) covers the actual need; reaching for Redux
here would be state-management machinery with nothing non-trivial to
manage.

### Why is role-based UI gating duplicated client-side when the backend already enforces RBAC?
Hiding nav links and blocking direct navigation (`RequireRole`) for a
technician on `/approvals` or `/audit-log` is a UX courtesy — it stops a
user from clicking into a page that will just 403 — not a security
boundary. The backend's `require_roles` (Phase 1/7) is the actual
enforcement, verified independently by the existing 201 backend tests;
the frontend check is defense in depth, live-verified this phase by
confirming a technician session gets both the hidden nav item and a
redirect on direct navigation, while the underlying API call still
correctly 403s regardless of what the UI shows.

### Why does the Docker-built frontend get `VITE_API_BASE_URL=http://localhost:8000` baked in at build time, not proxied through nginx to the `backend` service?
Vite env vars are resolved at build time into the static JS bundle, and
the code that calls the API runs in the user's browser, not inside the
frontend container — so the URL has to be one the *browser* can reach
(`localhost:8000`, published on the host), not the Docker-internal
service name (`http://backend:8000`, which only resolves on the compose
network). This is the same "browser vs. container network" distinction
that shaped the Phase 1 CORS setup; live-verified by confirming an actual
cross-origin login request from the Docker-served frontend (origin
`http://localhost:3002`) reaches the backend and gets a real (401)
response, not a CORS or DNS failure.

### Why a separate `docker-compose.yml` port for the frontend (3002) instead of the conventional 3000?
Ports 3000 and 3001 on this machine were already bound by containers from
another portfolio project running concurrently — a genuine, mundane
multi-project workspace conflict, not a design decision. Remapped to
`3002:3000` (container still listens on 3000 internally) and
`CORS_ORIGINS` updated to match; the general lesson (check `lsof`, pick a
free host port, keep `CORS_ORIGINS` in sync in both `.env` and
`.env.example`) is the same remediation used for every port conflict
across this project's earlier phases, not new to this one.

### Why does the frontend's Dockerfile `HEALTHCHECK` use `127.0.0.1`, not `localhost`?
Found while checking `docker compose ps` during Phase 9: the frontend container reported `unhealthy` despite serving real traffic correctly (confirmed via `curl` from the host and live browser use in Phase 8). `docker exec`-ing into the container showed why — nginx binds `0.0.0.0:3000` only (IPv4, matching `nginx.conf`'s plain `listen 3000;`), but this image's `wget` resolves `localhost` to `::1` first and doesn't fall back to IPv4 on refusal, so the healthcheck's own request failed even though the exact same request against `127.0.0.1:3000` succeeded from inside that same container. A real bug that predated this phase (introduced in Phase 8, not caught then because verification checked the app's actual behavior, not `docker compose ps`'s health column) — fixed by pointing the healthcheck at the IPv4 literal directly, sidestepping DNS resolution order entirely rather than trying to force IPv6 or dual-stack binding for a healthcheck that doesn't need it.

## Phase 9

### Why Prometheus + Grafana instead of relying on the structured logs already in place since Phase 1?
Structured JSON logs (Phase 1, `app/logging_config.py`) answer "what happened on this one request" — they're the right tool for debugging a specific failure, but not for "how is the system behaving over the last hour," "is p95 latency drifting," or "how much is the LLM actually costing per diagnosis." Those are aggregate, time-series questions, which is exactly what a metrics system is for. Prometheus's pull model needs nothing more from the app than a `/metrics` endpoint (no agent, no external service dependency for local dev), and Grafana turns the same data into something an interviewer can actually look at, not just described. Logs and metrics stay complementary, not a replacement for each other — the request-ID/duration-per-request log line from Phase 1 is untouched.

### Why is LLM/VLM/agent cost tracking config-driven (`*_COST_PER_1K_USD`, default 0.0) instead of a hard-coded per-model price table?
This project's standing rule is never to present a fabricated number as real. A hard-coded price is a claim about the world at a point in time — provider pricing changes, and baking in a guessed or stale figure would be exactly the kind of unverified "metric" this project explicitly avoids elsewhere (see the Phase 3 citation-validation and Phase 4 measurement-flagging entries — the same principle, applied to cost). Token *counts* come directly from the provider's own `usage` field on every response, so those are tracked unconditionally and are always real; the dollar figure only appears once someone supplies their own current rate via settings, at which point it's their number, not this project's guess.

### Why does route-templated HTTP metrics labeling matter here specifically (`request.scope["route"].path`, not `request.url.path`)?
Several routes carry a UUID path parameter (`/api/v1/diagnoses/{diagnosis_id}`, `/api/v1/documents/{document_id}`, etc.) — labeling by raw path would make every request to the same endpoint its own Prometheus time series, and an unauthenticated scan/bot hitting random paths would create an unbounded number of series (a real operational hazard called "cardinality explosion," not a hypothetical one). Using the matched route's pattern instead means `/api/v1/diagnoses/{diagnosis_id}` is one series regardless of which diagnosis, and anything that doesn't match a route collapses to a single `"unmatched"` label rather than leaking the attempted path into a metric label forever.

### Why does this phase not instrument the Celery worker (document ingestion)?
The worker runs as multiple forked processes (`--concurrency=2`) and doesn't serve HTTP — `prometheus_client`'s default in-process registry isn't safe to scrape across forked processes without `PROMETHEUS_MULTIPROC_DIR` (a file-based aggregation mode with its own setup and failure modes), and a worker with no HTTP server has nothing for Prometheus to scrape without adding a second small server process just for metrics. That's real, separate infrastructure work whose payoff (visibility into ingestion pipeline timing) is smaller than the request/LLM/agent path this phase covers, and document status is already visible via DB polling (Phase 2/8). Scoped out explicitly, not silently skipped — worth adding if ingestion latency ever becomes something to actively debug.

### Why is `/metrics` unauthenticated, unlike every other endpoint in this API?
Prometheus's scraper has no user session and no bearer token to present — requiring JWT auth on `/metrics` would mean either giving Prometheus a standing credential (a real secret-management problem for a metrics scraper) or the endpoint simply never getting scraped. This matches standard Prometheus practice: the real access control for `/metrics` is network-level (only the scraper's network can reach it), not application-level. Locally, that boundary is the Docker compose network — the docker-compose port mapping is honest about the trade-off (host port 8000 also exposes it), which a real deployment would close by firewalling the metrics port to the Prometheus network specifically. Documented here rather than left implicit, since it's the one endpoint in this API that deliberately breaks the "everything needs a token" pattern.

## Phase 10

### Why structural/deterministic scoring (tool_recall, evidence_type_coverage, citation_validity_rate, meets_severity_floor) instead of an LLM-as-judge quality score?
Grading a diagnosis's free-text quality with another LLM call would itself be an unverified metric — a judge score with no way to check the judge's own reasoning is exactly the kind of "trust the model" evaluation this project avoids everywhere else (see Phase 3's citation validation, Phase 4's measurement-flagging, Phase 9's cost-tracking honesty). Every metric this harness reports instead reads off something either hand-labeled and inspectable (`required_tools`/`expected_evidence_types` per scenario, in `data/evaluation/diagnosis_scenarios.json` — the same category of ground truth as Phase 3's `expected_sources`) or already deterministically enforced by the agent loop itself (citation validation and severity escalation, both Phase 6). The trade-off is real and stated, not hidden: this can't tell you whether a diagnosis's prose reasoning is *good*, only whether the agent gathered the evidence a labeled scenario expects and whether its own invariants held.

### Why does `evaluation/diagnosis_eval.py` require a real `ANTHROPIC_API_KEY` and exit cleanly rather than run at all without one, unlike `evaluation/run.py` (retrieval)?
Retrieval evaluation (Phase 3) exercises embeddings/BM25/reranking, all local models — no external call needed, so it always produces a real report. This harness is evaluating the agent's own tool-selection and reasoning behavior, which has no local stand-in; a version that ran with a scripted fake model would be testing this harness's Python code (already covered separately by unit tests and a one-off wiring check this phase), not the actual model's behavior, and presenting that as an "evaluation report" would misrepresent what was measured. Exiting cleanly with a clear message on the missing-key path — rather than crashing, or worse, writing a report of all-zero/placeholder metrics that could be mistaken for a real result — is the same honesty rule already applied to the diagnosis agent itself (Phase 6) and vision analyzer (Phase 4) on this exact missing-key condition.

### Why reuse the "evaluation" tenant and existing seed scripts (`scripts/seed_sensor_data.py`, `scripts/seed_equipment_data.py`) instead of new fixtures for this phase?
Both scripts already default to the `evaluation` tenant specifically so the same demo tenant has manuals (Phase 3), sensor history (Phase 5), and equipment/maintenance data (Phase 6) together — this phase's scenarios (`data/evaluation/diagnosis_scenarios.json`) are written directly against that existing, already-verified synthetic story (the 5 injected MOTOR-001 vibration spikes, the deliberately-overdue CONVEYOR-001 maintenance task) rather than inventing a second, parallel set of fixtures with its own story to keep straight. Both seed calls are idempotent (skip what's already there), so running this harness never duplicates data even across repeated runs.

### Why is `min_severity` only set on one of the five scenarios?
A severity floor is only asserted where it's grounded in a rule the codebase already enforces deterministically — the `motor_vibration` scenario's `min_severity: "medium"` follows directly from Phase 6's `normalize_severity` escalation (a detected sensor anomaly forces at least "medium" regardless of what the model itself concludes), and Phase 5 already confirmed the seeded vibration spikes are actually detected as anomalies. None of the other four scenarios have an equivalently deterministic floor to check — asserting one anyway would be grading the model against this project's own guess at the "right" severity, not against anything actually verified, which is the same over-claiming this harness's scoring choices avoid elsewhere in this phase.

## Phase 11

### Why does this phase both `git init` this project and set up CI in the same pass, rather than CI on top of pre-existing history?
This project had no git history at all through Phase 10 — ten phases of work existed only as files on disk, verified live in Docker each time but never committed. CI/CD needs a real commit history to trigger against, so this phase reconstructs that history as one commit per phase (matching each phase's actual scope: files genuinely new to a phase, plus the handful of shared/evolving files — `docker-compose.yml`, `requirements.txt`, `app/main.py`, `app/config.py`, `README.md`, this ADR doc, `.env.example` — rebuilt to their state at each phase boundary using this project's own phase-by-phase documentation as the record of what changed when) rather than one large "everything as of today" commit. The reconstruction is a good-faith, well-documented approximation, not a byte-for-byte replay of the actual editing session — a small number of very early micro-fixes with no preserved exact diff (e.g. a type-hint bug mentioned in passing in Phase 7's own notes) aren't separately represented, since fabricating a plausible-looking historical bug to show a plausible-looking fix would be exactly the kind of invented-but-unverifiable content this project avoids everywhere else.

### Why three separate CI jobs (backend, frontend, compose-smoke-test) instead of one?
Each job catches a different, independent class of regression, and running them in parallel means a frontend-only change doesn't wait on the backend suite or vice versa. `backend` is fast unit/lint feedback (ruff + pytest against sqlite, same as local `make test`). `frontend` catches TypeScript/build breakage and — via a `docker build` step on the same job — a broken frontend Dockerfile, which nothing else in CI would otherwise exercise. `compose-smoke-test` exists because this project's own standing rule, applied manually every phase so far, is "verify in Docker against real infra, not just unit tests with mocks" (see the very first build-conventions entry from Phase 1) — CI is where that discipline stops depending on a human remembering to do it by hand each time and becomes something that runs on every push instead.

### What does the compose smoke test actually verify, and why not more?
It builds the real backend image from the real Dockerfile, brings up `backend` + `worker` through docker-compose's own `depends_on`/`healthcheck` chain against real Postgres/Qdrant/Redis (not mocked or skipped), waits for the health endpoint, and round-trips a real register → JWT → authenticated `/me` request — the same category of check this project has run by hand via `curl` after every single phase in this build. It deliberately does not also bring up `frontend`/`prometheus`/`grafana` or exercise the diagnosis agent (which needs a real `ANTHROPIC_API_KEY` CI doesn't have, same standing limitation as everywhere else) — scoped to keep CI runtime reasonable and to cover the core request path that every other feature in this project sits on top of, not to claim exhaustive coverage.

### Why is this phase's CI/CD setup not live-verified against a real GitHub Actions run, unlike every other phase's Docker verification?
Running a GitHub Actions workflow requires an actual GitHub remote and a push — this session's environment has neither `gh` CLI authentication nor an existing repository to push to, and creating one plus pushing code is an action with real external consequences (a public/private repo appearing under someone's account) that this project's operating rules require the user to explicitly authorize and perform, not something to do unprompted on their behalf. The workflow was still built with the same rigor as everything else: every script/endpoint path it references was cross-checked against the actual route definitions and `package.json` scripts (not assumed), its YAML was syntax-validated, and its system-dependency list (`tesseract-ocr`, `poppler-utils`) was derived from the same packages the Dockerfile already installs for the identical reason (`app/ingestion/ocr.py`'s tests exercise real binaries, not mocks). What's genuinely unverified is only the one thing that can't be checked without a real GitHub remote: whether the workflow actually goes green when GitHub runs it — documented here the same way the no-API-key limitation is documented elsewhere, rather than silently assumed to work.

## Phase 12

### Why `docs/security.md` now, as a consolidation, instead of writing it once and updating it phase by phase?
The ADR's own Phase 3 entry on prompt-injection defense promised this file back when the diagnosis agent's tool-calling made that concern concrete — a promise that sat unfulfilled through Phases 4-11 (caught only now, while surveying the repo for this final phase, not because anyone flagged it). Writing it as a single consolidation at the end, rather than incrementally, was deliberate here specifically: by Phase 12 every security-relevant mechanism it describes (RBAC, tenant isolation, upload validation, citation validation, tool-scoping, audit logging) already exists and is already tested, so the document could be written entirely by reading and citing real code (`app/core/security.py`, `app/core/deps.py`, `app/services/document_service.py`, etc.) rather than describing a mechanism that was still being designed. Every claim in it points at a specific file or test, the same discipline as every other doc in this project.

### Why MIT license, chosen without asking?
A license choice for a public portfolio/demo repository is a low-stakes, easily-reversible preference, not an architectural decision with real trade-offs to weigh (unlike, say, the Phase 9 observability-stack scope or the Phase 11 git/CI approach, both of which were put to the user first) — MIT is the de facto default for exactly this kind of repository, and getting it wrong costs a one-line file edit, not a redesign.

### Why a Mermaid architecture diagram instead of screenshots for this final README pass?
Screenshots were the original plan (the README has said "screenshots" as a later-phase promise since Phase 1) — attempted this phase by driving the live frontend and taking browser screenshots, but this session's tooling has no path from a captured screenshot to a saved image file that could be committed to the repo and referenced from Markdown, only an inline view for the conversation itself. A Mermaid diagram sidesteps this entirely (renders natively on GitHub from a text code fence, no binary asset to generate or keep in sync) and has a real advantage screenshots don't: it can't go stale the way a UI screenshot does the next time a page's styling changes, since it's describing the system's data flow, not its current pixel layout. Documented here as a substitution made for a concrete tooling reason, not a silent scope-cut from the original promise.

### Why does the CI `backend` job need a Qdrant service container, when the test suite otherwise runs fine against sqlite alone?
The first real GitHub Actions run (right after pushing) failed exactly this way: `tests/test_document_upload.py` and `tests/test_document_audit_log.py` both hit `qdrant_client.http.exceptions.ResponseHandlingException: [Errno 111] Connection refused`. The sqlite fixture (`tests/conftest.py`) only stands in for Postgres — `app/rag/qdrant_store.py:get_qdrant_client()` always constructs a real `QdrantClient` pointed at `settings.qdrant_host`/`qdrant_port` (never mocked, same "verify against real infra" choice as everywhere else in this project), and document deletion's Qdrant-point cleanup exercises that real client. This never surfaced locally because every local test run went through `docker compose run`, where Qdrant is always up as a sibling service — the gap was specific to the CI job's bare-runner environment, which the local Docker workflow could never have caught. Fixed with a `services: qdrant:` block on the `backend` job (same `qdrant/qdrant:v1.12.4` image pinned in `docker-compose.yml`), and verified the fix directly before pushing again: started a standalone Qdrant container on the same port locally and re-ran the two failing test files against it through the real backend image — 8/8 passed, not just "should work" reasoning from reading the error.

### Why split the phase-by-phase build log out of the README into `docs/implementation-log.md`?
The README had grown to roughly 660 lines, the large majority of it the "Implemented so far" section's twelve phase-by-phase bullet blocks — real content, but it buried the parts a first-time visitor actually needs first (what this is, how to run it, the architecture). Moved verbatim into its own file, with the phase-number heading prefixes (`Phase 1 — Foundation`, etc.) dropped in favor of just the area name (`Foundation`) — the numbering mattered while phases were still in progress and being verified one at a time; once the build is finished, "Foundation" is what the section actually is, and "Phase 1" is an implementation-order detail more relevant to the git history and this ADR than to a reader trying to understand what the system does. The README now links to it as a single short section rather than inlining it. Inline `Phase N` references *within* prose elsewhere (this ADR's own organization, and a few scattered cross-references in the README/implementation log) were left as-is — those carry real sequencing information (e.g. "Equipment deferred until this tool needed it"), unlike the section headers, which were purely chronological labels.

## Fix Pass (post-Phase-12 audit)

A full read-only audit of the finished 12-phase MVP (see `docs/security.md`
and this file's own entries for what was already verified) surfaced four
categories of real, verified gaps: rate limiting was configured but never
enforced on any route; a dead RAG-generation implementation coexisted with
the diagnosis agent's live one; the AI pipeline's test coverage skipped the
happy path for vision and had no retry/backoff for transient provider
failures; and a few smaller correctness/security items (filename display,
conversation cross-user scoping, a bounded-memory gap) were found in
passing. This section documents the fixes, in the same why-not-just-what
style as the rest of this log.

### Why was rate limiting configured but not enforced, and how was that actually fixed (not just re-configured)?
`app/main.py` registered `app.state.limiter` and a `RateLimitExceeded`
exception handler, which looks like enforcement but isn't — slowapi only
rate-limits a route that carries its own `@limiter.limit(...)` decorator;
nothing in the codebase had one. The fix is a shared `app/core/rate_limit.py`
module (a separate file specifically to avoid a circular import: route
modules need to import the `Limiter` instance, and `app/main.py` imports
every route module to register its router) plus four explicit decorators —
auth register/login, document upload, image analyze, copilot query — each
with its own configurable limit (`RATE_LIMIT_AUTH`/`_UPLOAD`/`_AI`). Verified
two ways, not just by reading the code: `tests/test_rate_limit.py` drives
real request sequences through the test client past each limit and asserts
the 429, and a live `curl` loop against the actually-running Docker
container confirmed the same 429-at-the-configured-threshold behavior
outside the test suite. A `limiter.reset()` was added to the `client`
fixture (`tests/conftest.py`) — slowapi's in-memory limiter state is a
module-level singleton that otherwise persists across the whole pytest
process, which would have made unrelated tests spuriously fail once limits
were actually enforced.

### Why keep `app/rag/generation.py` at all, rather than deleting it once its dead functions were removed?
The file's `generate_answer`/`_format_sources`/index-marker citation parser
had zero production callers by the time of the audit (confirmed by
repo-wide grep) — a leftover single-shot-QA design superseded by the
Phase 6 agent's own inline Anthropic call in `diagnosis_agent.py`, which
had grown its own `_call_anthropic`/`_call_model`/`ModelTurn`/`ModelToolCall`
directly inside the agent module. Rather than just deleting the dead code
and leaving the live LLM-call step embedded in the agent loop, it was moved
into this file (renamed to `call_model`) — this literally realizes "one
canonical generation service the agent calls into" using the *real* live
implementation, instead of leaving a now-empty module or, worse, force-
fitting the dead index-marker citation design into the agent's actual
string-set citation validation (which would have been a real architecture
change to a system already working correctly, not a cleanup). Verified via
repo-wide search afterward that exactly one `ModelTurn`/`ModelToolCall`
definition and one model-call implementation exist. A second, unplanned
consequence of this move: `app/llm/client.py`'s provider-agnostic
`chat_completion` helper turned out to have no callers left either once
`generate_answer` was gone (it was never used by the agent — see the
Phase 3 LLM_PROVIDER correction above) — trimmed to just the shared
`LLMError` exception type, which both `app/rag/generation.py` and
`app/vision/analyzer.py` still raise/catch.

### Why does retry/backoff wrap only the single external call, and why exclude some Qdrant call sites?
`app/core/retry.py`'s `call_with_retry`/`call_with_retry_sync` wrap just
the raw SDK call (`client.messages.create(...)`, `client.query_points(...)`),
not the surrounding function — retrying a parsing bug by mistake (if the
whole function were wrapped and a bug lived in response-parsing code) would
silently turn a real defect into a slow, pointless retry loop instead of a
clear, immediate failure. Retryable errors are an explicit allowlist
(`is_transient_llm_error`/`is_transient_qdrant_error`) — timeouts,
connection errors, rate limits, and 5xx — never auth/validation/malformed-
request errors, which retrying cannot fix. Applied to the diagnosis agent's
LLM call, both vision providers, and Qdrant's read path (`search`, on the
critical per-diagnosis-query path) plus the two ingestion-time Qdrant
writes (`ensure_collection`, `upsert_chunks`) — those two are safe to retry
because retrying the *same* upsert call with the *same* point_ids is
idempotent. Deliberately NOT extended to a Celery-task-level retry on
`ingestion.process_document_version` (`max_retries` stays `0`, with the
reasoning recorded directly in `app/tasks/ingestion_tasks.py`): that
function generates a fresh `uuid4()` point_id and `DocumentChunk` row per
chunk on every invocation, so a whole-task retry after a partial success
(Qdrant write succeeded, then the process died before the Postgres commit)
would insert a *second*, duplicate set of chunks rather than safely
repeating the first attempt — making it retry-safe would need deterministic
point IDs or a delete-before-insert step, a real change to the ingestion
write path, not something to bolt on alongside a retry fix.

### Why does exhausting retries now raise a wrapped `LLMError`/`VisionError` instead of the raw SDK exception?
Before this fix, only the two *deliberate* domain errors (no API key
configured; the model returned unparseable JSON) were caught by
`run_diagnosis`'s `except (LLMError, AgentError)` and
`analyze_uploaded_image`'s `except VisionError` — a raw
`anthropic.APITimeoutError` from the SDK call itself was never caught by
either handler and would have propagated as an unhandled exception (a bare
500, not a clean "failed" record with a real error message), both before
*and* after retries were added — retrying doesn't change what happens on
final exhaustion, just how many attempts happen first. Wrapping the final
exception (message preserved, `raise ... from exc`) at the same two call
sites that added retry closes this gap with no separate new code path: a
provider outage after retries are exhausted now produces the exact same
graceful "failed" diagnosis/image-analysis record as a malformed-JSON
response always has, instead of two different failure UX depending on
*which* provider error occurred. Covered by
`tests/test_retry.py::test_vision_analyze_image_final_error_after_exhausted_retries`
and the HTTP-level equivalent in `tests/test_vision_integration_mocked.py`.

### Why does the mocked VLM/E2E test suite mock the Anthropic SDK client class, not the analyzer/agent functions themselves?
The audit's own instruction for the VLM test ("don't mock the whole
analyzer, only the provider call") generalizes to every AI-pipeline test
added in this pass: `tests/test_vision_integration_mocked.py` and
`tests/test_e2e_diagnosis_pipeline_mocked.py` both monkeypatch
`anthropic.AsyncAnthropic` itself (a fake class whose `messages.create`
returns scripted responses, routing by whether `tools=` was passed, since
the vision call and the agent's tool-calling call share this one SDK entry
point) — everything above that boundary (HTTP routes, upload validation,
preprocessing, response parsing, DB persistence, citation validation,
confidence/severity computation, the approval workflow, audit logging) runs
for real. The E2E test goes one step further for hybrid RAG specifically:
only the Qdrant *dense* leg (`app.rag.retrieval.qdrant_dense_search`) is
mocked (returns no hits) — real BM25 retrieval, real RRF fusion, and the
real local cross-encoder reranker all run against chunks seeded directly
into the (SQLite, test-isolated) Postgres fixture, rather than mocking
`hybrid_search` wholesale. This surfaced a genuine subtlety worth recording:
BM25's IDF formula (`log((N - freq + 0.5) / (freq + 0.5))`) is exactly zero
when a query term appears in exactly 1 of 2 corpus documents — a real
keyword match against a single-chunk or two-chunk fixture silently scores
`<= 0` and gets filtered out by `app/rag/bm25.py`'s `score > 0` keep
condition. The E2E fixture needed a *third*, topically distinct chunk
before the target term's IDF went positive — not a bug in the retrieval
code, an inherent property of BM25 over a near-empty corpus that a fixture
with too few documents would silently mask.

### Why sanitize the *displayed* filename at the point of storage into `Document.original_filename`, rather than at each display site?
Path-traversal was never actually exploitable — uploaded files are always
written under a UUID-based path (`f"{version_id}.pdf"`,
`app/services/document_service.py`), so a malicious client filename could
never become a filesystem path. `app/core/filenames.py:sanitize_display_filename`
is a second, independent layer: it strips directory components (both POSIX
and Windows separator styles), control characters, and filesystem-reserved
characters from `original_filename` *before* it's stored, so every
downstream consumer (API responses, the frontend, PDF diagnostic reports,
logs) automatically gets a clean value without each one needing to
remember to sanitize it separately — a single choke point instead of a
policy to repeat at every render site. Deliberately not an ASCII-only
allowlist: accented characters and non-Latin scripts are legitimate in real
filenames, so the filter is a blocklist (control chars, path separators,
`<>:"|?*`) rather than an allowlist that would have mangled them.

### Why does a conversation's existing-thread lookup now filter by `user_id`, not just `tenant_id`?
Found in passing while adding bounded conversation memory (below), not
flagged by the original audit: `_get_or_create_conversation`'s reuse
lookup, and `get_conversation`'s detail-view lookup, both filtered only by
`tenant_id` — meaning any user in the tenant who learned another user's
`conversation_id` (a UUID, but not literally unguessable — e.g. leaked via
a shared link or a log line) could read that conversation's full message
history, and passing it into `run_diagnosis` would have silently attached
a new diagnosis to a thread that wasn't the caller's. `list_conversations`
was already scoped by `user_id` — this was an inconsistency between the
list and detail paths, not an intentional shared-thread design. Both now
filter by `user_id` too; a mismatched user creates a fresh conversation
instead of reusing someone else's. This became a materially bigger deal
once conversation memory (below) started actually feeding prior message
content back into the model — previously the gap was "you could view
someone else's diagnosis," now it would also have been "your follow-up
question's context could get contaminated with another user's thread."

### Why fold prior context into the current turn's single initial message, instead of replaying the previous run's raw tool-calling messages?
Before this pass, a `conversation_id` was purely a grouping/UI-threading
mechanism — the model received zero memory of prior turns even when
reusing an existing conversation; `_build_initial_message` always started
from a single fresh user message. The fix
(`app/agents/diagnosis_agent.py:_fetch_recent_context`) is bounded (last 6
messages = 3 Q&A exchanges, each capped at 1000 characters) and reads back
as plain text folded into *this* turn's one initial message, explicitly
labeled "background only... NOT verified evidence for this diagnosis" —
not a replay of the previous `run_diagnosis` call's raw multi-turn
`tool_use`/`tool_result` message array, which would have referenced
`tool_use_id`s that don't exist in this fresh model conversation and would
be invalid to send. The explicit "not evidence" framing matters for the
same reason citations are validated against real gathered evidence
elsewhere in this project: without it, the model could cite a *prior*
diagnosis's conclusion as if it were freshly verified support for a new
`possible_causes[].supporting_citations` entry, silently bypassing
`_validate_causes`'s guarantee that every citation matches something
actually retrieved in the current run.

### Why does `process_document_version_sync` dispose the SQLAlchemy engine after every task, when the FastAPI backend never needs to?
Found while preparing a terminal demo recording, not by the earlier audit:
uploading a second document through the same long-lived Celery worker
process failed with `RuntimeError: ... got Future ... attached to a
different loop`. `app/database.py`'s `engine` is a module-level singleton
shared by the whole worker process, but
`process_document_version_sync` wraps every task in its own
`asyncio.run(...)` — which opens a *new* event loop per task and closes it
on return. An asyncpg connection is bound to the event loop that created
it, so the pool's connection from task 1 was still sitting in the pool
when task 2's `asyncio.run()` handed it a different, freshly-created loop
— `pool_pre_ping`'s own liveness check is what actually throws, since even
pinging the stale connection requires running on the loop that owns it.
The FastAPI backend process never hits this: uvicorn runs one event loop
for the process's entire lifetime, so `engine`'s pooled connections are
always used from the same loop that created them. The fix
(`app/services/ingestion_service.py:_process_and_dispose_engine`) disposes
the engine in a `finally` block at the end of every task, in the same
event loop that owns the connections being disposed — the next task's
`asyncio.run()` then starts with an empty pool bound to its own loop.
Verified by running two document uploads back-to-back against the same
long-lived worker container (not `docker compose run --rm`, which would
never have reproduced this) — failed before the fix, passed after.

### Why did dense retrieval need a chunk-id translation step, and how was this found?
Found during a rigorous retrieval ablation (evaluating each hybrid-search
component in isolation — BM25-only, dense-only, hybrid+RRF, hybrid+RRF+
rerank — against the same ground-truth question set `evaluation/run.py`
already uses), not by the earlier audit or the Fix Pass: `dense_only`
scored exactly 0.0 on every metric. Traced to `app/rag/retrieval.py:hybrid_search`
— Qdrant is indexed under its own `uuid4()` point ID, generated
independently at ingestion time and stored separately as
`DocumentChunk.qdrant_point_id` (`app/services/ingestion_service.py`), but
`hybrid_search`'s dense results were being filtered directly against
`rows_by_id`, which is keyed by `DocumentChunk.id` — confirmed by direct
query that these are never equal for any row. Every dense hit was
therefore silently dropped before it could reach RRF fusion, meaning
"hybrid retrieval" had actually been running as BM25-only since Phase 3 —
a real correctness bug, not a design tradeoff, and a README/ADR claim that
had been false the entire time it existed. Fixed by translating dense
results through `qdrant_point_id -> DocumentChunk.id` right after the
Qdrant call (`_fetch_candidates` now also selects `qdrant_point_id`);
everything downstream (BM25 corpus keys, RRF, reranking, the final
`RetrievedChunk` construction) is untouched.

Re-measured after the fix (`evaluation/retrieval_ablation.py`, same 7-question
benchmark): `dense_only` MRR 0.929, `hybrid_rrf` (no rerank) 0.905,
`hybrid_reranked` (production config) 0.886, `bm25_only` 0.878. The
reranker very slightly *lowers* MRR relative to unranked RRF fusion on
this specific benchmark — reported as measured, not tuned away, per this
evaluation's own rule against optimizing the benchmark for a better
number. With only 7 questions this is not strong enough evidence to
conclude the reranker is net-harmful in general; it's recorded as a real,
reproducible result on a small internal benchmark, not a general
performance claim. See `EVALUATION_AUDIT.md` for the full evaluation.
