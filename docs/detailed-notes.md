# Industrial Multimodal AI Copilot: detailed notes

> Earlier long-form README, kept for reference. The current overview is in the repository [README](../README.md).

Evidence-based diagnostic copilot for manufacturing technicians: combines a
technician's question, a component photo, sensor readings, and technical
manuals into a structured, cited diagnosis with confidence scoring and
human-in-the-loop approval for high-risk cases.

**Status: feature-complete (Phases 1–12 of the original build plan).**
Built incrementally, phase by phase, with every phase verified live
against real Postgres/Qdrant/Docker before moving to the next — not just
unit tests. See [`docs/architecture-decisions.md`](architecture-decisions.md)
for the design rationale behind every non-obvious choice below, and
[`docs/security.md`](security.md) for the security model
specifically.

![Demo: create a workspace, dashboard, admin adds a supervisor, real manual upload through the ingestion pipeline, AI Copilot query form](images/demo.gif)

*Real app, real backend, real data — creating a company workspace (you
become its admin), the dashboard, adding a supervisor from the Users page,
a manual upload going through the real ingestion pipeline to "ready", and
the AI Copilot query form. Captured directly against the running stack, not
staged.*

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
- Multi-tenant security: sign-up creates your own
  company workspace (nobody can join another company or pick their own
  role), role-based access enforced server-side, per-tenant data
  isolation, token revocation, and audit logging — see
  [`docs/security.md`](security.md)
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
See [`docs/usage-guide.md`](usage-guide.md#try-the-diagnosis-agent) to
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
- **Auth & tenancy**: JWT auth with logout revocation (Redis blocklist);
  sign-up creates a new company workspace with you as its admin, and admins
  add supervisors/technicians from a Users page; every query scoped to the
  caller's tenant
- **Human-in-the-loop**: role-gated supervisor approve/reject workflow —
  a supervisor can't sign off on their own diagnosis, and each diagnosis
  is decided exactly once — plus an append-only audit log
- **Frontend**: React 19 + Vite + TypeScript, hand-rolled CSS design
  system, role-aware SPA (Dashboard, Knowledge Base, AI Copilot, Evidence
  panel, Approval Dashboard, Users, Audit Log)
- **Observability**: Prometheus metrics (HTTP, LLM/VLM calls + token usage,
  agent tool calls, diagnoses, approvals) + Grafana dashboard, on top of
  structured logging (structlog)
- **Infra**: Docker Compose (all ports bound to localhost, password-protected
  Redis), GitHub Actions CI

## Results

Retrieval ablation on the project's 7-question ground-truth set (`python -m evaluation.retrieval_ablation`; raw results in `data/evaluation/results/`):

| Retrieval configuration | MRR |
|---|---|
| Dense only | 0.929 |
| Hybrid (RRF), no rerank | 0.905 |
| Hybrid + cross-encoder rerank (production config) | 0.886 |
| BM25 only | 0.878 |

The reranker very slightly *lowers* MRR here and is reported as measured, not tuned away. With only 7 questions the differences are small and this is a reproducible internal result, not a general performance claim. See Known limitations below for what is and is not evaluated.

## Local setup

```bash
cp .env.example .env   # then set ANTHROPIC_API_KEY if you want live LLM calls
docker compose up --build
```

Open http://localhost:3002 and choose **Create a workspace** — you become
that workspace's admin, and can add supervisors and technicians from the
**Users** page. (For anything beyond local use, set `APP_ENV=production`
along with a real `SECRET_KEY`, non-default Postgres/Redis passwords, and a
`METRICS_TOKEN` — the app refuses to start in production without them.)

No budget for API credits? Run everything on free local models with
[Ollama](https://ollama.com) — no key, no cost:

```bash
ollama pull qwen2.5:7b      # diagnosis agent (tool calling)
ollama pull qwen2.5vl:3b    # component-photo analysis
```

then in `.env` set `LLM_PROVIDER=openai`, `LLM_MODEL=qwen2.5:7b`,
`LLM_BASE_URL=http://host.docker.internal:11434/v1`, and
`VISION_PROVIDER=openai`, `OPENAI_VISION_MODEL=qwen2.5vl:3b`,
`VISION_BASE_URL=http://host.docker.internal:11434/v1`. Both paths run end
to end this way (16 GB RAM is enough); see Known limitations for how the
results compare.

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

## MCP server

The seven diagnostic tools are also exposed as a standalone [MCP](https://modelcontextprotocol.io) server (`app/mcp_server/`), so any MCP client can call them. It reuses the same tool schemas and executor as the in-app agent, so tenant scoping and citation strings behave identically. It is scoped to one tenant via `MCP_TENANT_ID`; clients cannot pick a tenant.

Register it in your MCP client's server configuration (the `mcpServers` format most clients use), with the stack's Postgres running:

```json
{
  "mcpServers": {
    "industrial-copilot": {
      "command": "python",
      "args": ["-m", "app.mcp_server.server"],
      "cwd": "/absolute/path/to/industrial-copilot",
      "env": {
        "MCP_TENANT_ID": "acme",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/copilot"
      }
    }
  }
}
```

Failed tool calls come back as MCP errors rather than crashing the server. Covered by `tests/test_mcp_server.py`.

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
[`docs/usage-guide.md`](usage-guide.md) — kept out of this README to
keep the overview scannable.

## Implementation log

Full build-out, area by area — what was built and how each was
verified — lives in
[`docs/implementation-log.md`](implementation-log.md): Foundation,
Document Intelligence, RAG, Vision, Sensor Intelligence, Diagnosis Agent,
Human Approval, Frontend, Observability, Evaluation, CI/CD, Final Polish.

## Supervisor graph, RAGAS and load test (2026-10-07)

![Demo: a 20% confidence diagnosis held for review (invented citations discarded and disclosed), supervisor rejects it with a comment, then a 69% supervisor-graph diagnosis with real manual citations](images/supervisor-demo.gif)

*Recorded headlessly against the local Docker stack from diagnoses produced by the live `qwen2.5:7b` runs above; the page changes (rejecting the 20% one) are real UI actions.*

- **LangGraph supervisor** (`POST /api/v1/copilot/query/supervised`): a supervisor routes between
  documents / sensors / vision specialists, each limited to its own tools; synthesis reuses the
  single agent's citation validation and confidence scoring. When a diagnosis needs approval the
  graph pauses with `interrupt()` and the supervisor's approve/reject call resumes it. Checkpoints
  are in memory, so a server restart drops paused threads (the database approval record is unaffected).
  Live check on local `qwen2.5:7b`: completed in ~155 s, 5 evidence items, real manual citations,
  confidence 0.69, approval required. A first run exposed two bugs, both fixed: routing/synthesis were
  offered tools and returned tool calls instead of text, and the supervisor could skip every specialist.
- **RAGAS** (`python -m evaluation.ragas_eval`, own venv via `requirements-eval.txt`), 7 questions over
  the sample manual, judge = local `qwen2.5:7b`: faithfulness **1.00**, context precision (no reference)
  **0.91** (7/7 scored). Caveat: tiny set, one manual, and a 7B judge grading a 7B generator; read it as a
  sanity check, not a benchmark. Scores are exported to Langfuse (see below).
- **Locust** (`loadtest/locustfile.py`, AI endpoints skipped, 5 users, 45 s, local Docker, 95 requests,
  0 failures): `/health` avg 11 ms, `GET /diagnoses` avg 24 ms (p99 160 ms), login avg 1.6 s (password
  hashing). Light load on one laptop; AI endpoints are rate limited and model-bound, so not load-tested.
- **Provider switch** (`LLM_PROVIDER=groq|gemini`, key in `LLM_API_KEY`): groq and gemini use their
  OpenAI-compatible endpoints. **Live check on Groq (`openai/gpt-oss-120b`, free tier)**, same question and manual as
  the local run: single-agent `/query` completed in 7.0 s (confidence 0.80, 5 citations, approval required) and the
  supervisor graph in 8.5 s (confidence 0.72, real manual citations, approval required), versus about 155 s on the
  local 7B model. The run exposed one model quirk: gpt-oss sometimes tries to return its final JSON as a call to a
  non-existent tool and Groq rejects it (`tool_use_failed`); the client now retries once without tools, asking for
  plain JSON (unit-tested). One question on one model, not a benchmark. Gemini is wired the same way but has not
  been called live.
- **Injection screens, compared** (`python -m evaluation.injection_eval --llm-guard`; 20 hand-written synthetic attacks
  in `data/evaluation/injection_attacks.json`; benign = 7 real manual chunks + 15 synthetic tricky-benign sentences):

  | Screen | Attacks caught | False positives |
  |---|---|---|
  | Regex tripwire (`app/guardrails.py`, default) | 8/20 (direct 7/7, paraphrase/indirect/German/obfuscated 0/12) | 4/22 |
  | [llm-guard](https://github.com/protectai/llm-guard) `PromptInjection` (`INJECTION_SCANNER=llm_guard`, ~46 ms/call on CPU) | 15/20 | 2/22 |
  | Regex OR llm-guard | 18/20 | 6/22 |

  Flagged content is only *disclosed* in the diagnosis `limitations` (it is never dropped), so a false positive costs a
  note, not a wrong answer. Small, self-written sets: indicative, not a benchmark. The llm-guard scanner is optional
  (`pip install llm-guard`, downloads a local model on first use). The default is still the regex screen.
- **Langfuse** (self-hosted locally with Langfuse's official compose file; project created headlessly via
  `LANGFUSE_INIT_*`): `python -m evaluation.ragas_eval export-langfuse <report.json>` writes one trace per question
  (question, retrieved contexts, answer) with its RAGAS scores, plus a run-summary trace. Verified in the Langfuse UI:
  8 traces, per-question scores and the mean scores (faithfulness 1.00, context precision 0.91). Needs
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`. The same export runs automatically at the end of
  `ragas_eval score` when those are set.

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
- BM25 is built in memory from the tenant-scoped candidate set in Postgres
  and cached per process for 60 seconds, rather than kept as a persistent
  keyword index — fine at portfolio scale, documented as a scaling
  limitation in the ADR. A newly ingested manual can take up to that long to
  show up in keyword (not dense) results.
- **Claude path not live-verified**: no Anthropic API credits are
  available here, so the Claude agent and vision paths are covered by the
  mocked test suite only — no accuracy claim is made for them. The live
  smoke tests and evaluation harness run against Claude as soon as
  `ANTHROPIC_API_KEY` has credits.
- **Open-model path live-verified end to end** (Ollama on a 16 GB Apple M4,
  via the same OpenAI-compatible code path): a real photo of a worn mill
  motor analyzed by `qwen2.5vl:3b` (~40 s), then a full diagnosis by
  `qwen2.5:7b` (~2 min) that called four different tools (image analysis,
  sensor history, maintenance schedule, manual search), returned three
  ranked causes each cited to a real manual section, rated severity high,
  and routed the result to supervisor approval. What it showed honestly:
  - The 3B vision model gives shallow, sometimes inaccurate observations
    (it described the motor and a ladder but missed visible rust and dust,
    and miscounted the ladder steps).
  - Citations are structurally validated, but free-text sensor findings
    aren't — the 7B model claimed a reading was "above baseline" when no
    historical baseline existed. Treat sensor-finding prose as the model's
    reading, not verified fact.
  - `llama3.2:3b` picks reasonable tools but often returns an empty or
    unusable final answer; `qwen2.5:7b` is the smallest model here that
    produced a complete diagnosis. Smaller models also tend to re-query the
    same tool round after round, so when the tool budget runs out the agent
    asks once for a final answer from the evidence already gathered before
    giving up (`app/agents/diagnosis_agent.py`).
- Prometheus/Grafana observability covers the FastAPI backend (HTTP,
  LLM/VLM, agent, diagnosis, approval metrics) and the Celery worker (task
  counts/durations via a second scrape target,
  `observability/prometheus/prometheus.yml`).
- LLM/VLM cost tracking (`llm_cost_usd_total`) stays at zero unless you
  configure your own current provider rate — no price is hard-coded; token
  *counts* are always tracked from the provider's real usage response.

See [`docs/architecture-decisions.md`](architecture-decisions.md) for
the reasoning behind each of these.
