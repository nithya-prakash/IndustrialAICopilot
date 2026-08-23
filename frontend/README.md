# Industrial Copilot — Frontend

React 19 + Vite + TypeScript SPA for the
[Industrial Multimodal AI Copilot](../README.md) — see the project root
README for what this application does, the full stack, and how to run it
(`docker compose up --build frontend`, or `npm install && npm run dev`
for local hot-reload development).

## Structure

- `src/api/` — typed client wrappers around every backend endpoint
- `src/context/AuthContext.tsx` — the one piece of genuinely global client
  state (JWT + current user); everything else is server state fetched
  per-page
- `src/components/` — shared UI (badges, layout, route guards, the
  diagnosis/evidence view reused across pages)
- `src/pages/` — one file per route (Dashboard, Knowledge Base, AI
  Copilot, Approvals, Diagnosis Detail, Audit Log, Login/Register)
- `src/index.css` — the hand-rolled design system (CSS custom properties
  + utility classes) — see the root
  [`docs/architecture-decisions.md`](../docs/architecture-decisions.md)
  for why this isn't a UI framework

## Scripts

```bash
npm run dev      # Vite dev server with HMR
npm run build    # tsc -b && vite build
npm run lint     # oxlint
npm run preview  # preview a production build locally
```
