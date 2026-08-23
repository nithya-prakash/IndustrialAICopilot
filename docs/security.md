# Security

This document consolidates the security-relevant design decisions made
throughout this project. Most of these are also covered individually in
[`architecture-decisions.md`](architecture-decisions.md) as they came up
phase by phase — this page pulls them into one place, organized by
concern rather than by build order, and states the accepted gaps as
plainly as the things that are actually enforced.

## Authentication

- JWT bearer tokens (`app/core/security.py`), HS256, signed with
  `SECRET_KEY`. `access_token_expire_minutes` (default 60) bounds token
  lifetime.
- Passwords hashed with bcrypt via `passlib` — never stored or logged in
  plain text. `bcrypt==4.0.1` is pinned alongside `passlib==1.7.4`
  specifically (see `architecture-decisions.md`'s build-conventions
  history) because newer bcrypt releases changed truncation behavior in a
  way that breaks passlib's own backend probe.
- Every authenticated request re-fetches the user and checks
  `user.is_active` (`app/core/deps.py:get_current_user`) — deactivating a
  user blocks their existing, unexpired tokens on the very next request,
  not just future logins. This is a real, if partial, mitigation for the
  gap below.

**Known gap:** there is no token revocation/blocklist beyond the
`is_active` check above. A stolen token remains valid for the rest of its
(short, 60-minute-default) lifetime even if the user is not deactivated.
Documented as a known limitation since Phase 1, not discovered late.

## Authorization

- Role-based access control — `technician` / `supervisor` / `admin`
  (`app/models/user.py`) — enforced server-side via `require_roles()`
  (`app/core/deps.py`), applied as a FastAPI dependency on the route
  itself (e.g. `/api/v1/diagnoses/{id}/approve` requires
  `supervisor`/`admin`; `/api/v1/audit-logs` requires `admin`), not
  re-checked ad hoc inside a generic handler.
- The frontend also hides nav items and blocks client-side navigation for
  roles that can't use a feature (`frontend/src/components/
  ProtectedRoute.tsx`) — this is UX convenience only. The real boundary is
  the backend dependency above; a request that bypasses the UI entirely
  still gets a real `403`, live-verified in Phase 7/8.

## Multi-tenancy isolation

- Every tenant-scoped table (`Document`, `Diagnosis`, `SensorReading`,
  `Equipment`, `Conversation`, `AuditLog`, …) carries a `tenant_id`
  column, and every query that reads or writes one of these tables
  filters on the caller's own `tenant_id` — there is no code path that
  lets a request read another tenant's data by supplying a different ID.
  Covered explicitly by tests (`tests/test_document_upload.py` and
  others assert cross-tenant reads return empty, not an error that could
  leak existence).
- `tenant_id` comes from the authenticated user's own record
  (`user.tenant_id`), never from a request parameter — a client cannot
  ask to see a different tenant's data by passing a different tenant ID
  in the URL or body, because no endpoint accepts one.

## Input validation

- **Document upload** (`app/services/document_service.py`): `Content-Type`
  is checked, but is a client claim, not proof — the file is also checked
  for the real PDF magic bytes (`b"%PDF-"`) before being accepted, and
  size-limited (`MAX_UPLOAD_SIZE_BYTES`).
- **Image upload** (`app/services/image_service.py`,
  `app/vision/preprocessing.py`): the file is actually decoded with PIL
  (`Image.open().load()`), not just trusted by extension/header — a
  corrupt or non-image file fails validation rather than being stored or
  sent to a VLM. Re-encoding to a fresh JPEG buffer as part of this
  validation also strips EXIF metadata (phone photos commonly carry GPS
  coordinates) as a side effect of the same step, not a separate policy
  someone has to remember.
- Both upload paths store files under a generated identifier, not the
  client-supplied filename, avoiding path-traversal via a crafted
  filename.

## Prompt injection & tool-calling safety

Retrieved document chunks, tool outputs, and any other model-adjacent
content the system did not itself generate are treated as **untrusted
data**, not instructions:

- RAG generation (`app/rag/generation.py`, Phase 3) and the diagnosis
  agent (`app/agents/diagnosis_agent.py`, Phase 6) both instruct the
  model explicitly that retrieved/tool-result text may contain
  instruction-like phrasing (e.g. "ignore previous instructions") and
  that it must be treated as quoted content, never executed as a
  command. This is a **prompt-level defense** — documented as such, not
  claimed as a guarantee, since no prompt instruction is provably
  unbreakable.
- Citations are never trusted from model output directly. Every citation
  the model writes is checked against the set of citations that were
  actually returned by a real tool call this session
  (`app/agents/diagnosis_agent.py:_validate_causes`); anything that
  doesn't match is dropped and flagged in `limitations`, not silently
  kept. This means a prompt-injection attempt that tries to get the model
  to fabricate a citation cannot produce one that looks structurally
  valid — see `architecture-decisions.md`'s Phase 3 entry on citation
  validation for the full mechanism.
- The `calculate` tool (`app/tools/calculator.py`) evaluates expressions
  via a restricted AST walk, not `eval()` — even a fully successful
  prompt-injection that convinced the model to pass an arbitrary string
  to this tool cannot execute arbitrary Python.
- Every tool call runs inside a `ToolContext` scoped to the requesting
  user's own `tenant_id` (`app/tools/executor.py`) — a tool cannot be
  made to read another tenant's documents/sensor data/equipment records
  regardless of what the model is convinced to ask for, because the tool
  layer itself never receives a tenant ID from the model, only from the
  authenticated request.

## Rate limiting, CORS, and transport headers

- `slowapi` rate limiting, default `60/minute` per client (`app/main.py`),
  configurable via `RATE_LIMIT_DEFAULT`.
- CORS is an explicit origin allowlist (`CORS_ORIGINS`), not a wildcard —
  the frontend's dev server, Docker-served origin, and nothing else by
  default.
- Every response carries `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and (when
  `APP_ENV=production`) `Strict-Transport-Security`.
- A generated `X-Request-ID` is attached to every response and bound into
  the structured log context for that request — useful for tracing a
  specific request through logs without exposing anything sensitive.

## Secrets management

- No secret is hard-coded anywhere in the codebase — everything (JWT
  signing key, database credentials, LLM API keys) comes from
  `app/config.py`'s `Settings` (Pydantic Settings, reads `.env`).
  `.env` is gitignored; `.env.example` documents every variable with a
  safe placeholder, never a real value.
- `docker-compose.yml` passes secrets to containers via `env_file`, not
  baked into the image at build time (the one exception,
  `VITE_API_BASE_URL` for the frontend, is a public API base URL the
  browser needs anyway, not a secret).

## The `/metrics` endpoint is deliberately unauthenticated

Unlike every other endpoint in this API, `GET /metrics` (Phase 9) takes
no bearer token — Prometheus's scraper has none to present. The real
access control for this endpoint is meant to be network-level (only the
scraper's network can reach it), not application-level; in this local
Docker Compose setup that boundary is the compose network, and the port
mapping is honest about the trade-off (host port 8000 also exposes it
locally). A real deployment would close this by firewalling the metrics
port to the Prometheus network specifically, not by adding a token
Prometheus doesn't have a way to send.

## Audit logging

`AuditLog` (Phase 7, `app/models/audit_log.py`) is an append-only record
of compliance-sensitive actions — diagnosis creation/failure, approval
decisions, document upload/deletion — each entry naming the actor, the
resource, and action-specific detail. Readable only by `admin`
(`GET /api/v1/audit-logs`). Scoped to these specific actions rather than
every mutating endpoint in the system (documented as a scope limit in
`architecture-decisions.md`'s Phase 7 entry, not assumed complete) —
extending coverage to another action is the same `log_event()` call, not
new architecture.

## Known gaps (accepted, not hidden)

- No token revocation/blocklist beyond the per-request `is_active` check
  above.
- `/metrics` relies on network-level isolation that this local Docker
  Compose setup doesn't actually enforce (host port 8000 is reachable
  directly).
- The Celery worker process is not covered by the Phase 9 observability
  setup — see that phase's ADR entry for what adding it would take.
- Rate limiting is per-client-IP via `slowapi`'s default key function,
  which is easy to defeat behind a shared NAT/proxy in a way a real
  production deployment would need to account for (e.g. keying on
  authenticated user ID where available) — not addressed here, since this
  project's rate limiting exists to demonstrate the pattern, not to be a
  production-grade abuse-prevention system.
