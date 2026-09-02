# Usage Guide

Step-by-step walkthroughs for running every part of this system by hand —
migrations, evaluation harnesses, and a curl-driven tour of each pipeline.
See the [project README](../README.md) for the overview/architecture and
[`architecture-decisions.md`](architecture-decisions.md) for the *why*
behind what you'll see here.

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
non-fabricated by the agent loop's own validation), and whether severity
met a deterministically-grounded floor where one applies (e.g. the seeded
MOTOR-001 vibration anomalies should force at least "medium"). Deliberately
does **not** attempt an LLM-as-judge quality score on the diagnosis text —
see `architecture-decisions.md` for why that would be exactly the kind of
unverified metric this project avoids elsewhere.

**Requires `ANTHROPIC_API_KEY`** — unlike retrieval evaluation, there's no
local stand-in for the agent's own reasoning, so with no key configured
this prints `NOT RUN — LIVE MODEL CREDENTIALS NOT CONFIGURED` and exits,
rather than running against a fake model and presenting that as a real
report.

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
the README's Known limitations.

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
`require_roles` check is the real enforcement (see the ADR). For local
frontend development with hot reload instead of the Docker build:

```bash
cd frontend && npm install && npm run dev
```

## Try observability

```bash
docker compose up --build backend prometheus grafana
```

- **Raw metrics**: http://localhost:8000/metrics (Prometheus text format —
  unauthenticated by design, see the ADR)
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
the README's Known limitations), and the diagnosis/approval panels
populate as soon as you run the copilot/approval flows above.
