# clients/web/

React admin UI for Legal, Operations, and Data Owners.

**Stack (locked):** Vite, React, TypeScript, TanStack Router, TanStack Query, Tailwind, Bun.

Deploy target: Firebase Hosting in front of Identity-Aware Proxy.

**Agent rules:** [`AGENTS.md`](AGENTS.md)

---

## Local development

Terminal 1 — admin-api:

```bash
uv run --package admin-api uvicorn admin_api.main:app --reload --app-dir app/admin_api/src
```

Terminal 2 — web (from repo root or this directory):

```bash
cd clients/web
bun install
bun run dev
```

Vite proxies `/api/*` to `http://127.0.0.1:8000` so the dashboard can call `/api/healthz` without cross-origin setup.

Optional: copy `.env.example` to `.env` and set `VITE_ADMIN_API_URL` when not using the dev proxy.

---

## Scripts

| Command | Purpose |
|---------|---------|
| `bun run dev` | Dev server |
| `bun run build` | Production build to `dist/` |
| `bun run preview` | Preview production build |
| `bun run lint` | oxlint |
