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
never from the model); out of range -> flagged as an invalid marker and
dropped, not silently kept. This makes fabricated citations structurally
close to impossible rather than something caught by a post-hoc string
match against known document names — see `app/rag/generation.py` and
`tests/test_citations.py`.

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
not require a paid key. `LLM_PROVIDER=openai` with `LLM_BASE_URL` pointed
at a local Ollama server is a one-line config change to run entirely
without any API key — the call sites (`app/llm/client.py`) never need to
know which backend is actually serving the request.

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

