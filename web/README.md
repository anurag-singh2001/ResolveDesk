# ResolveDesk web app

React 18 + TypeScript + Tailwind, built with Vite. It talks only to the HTTP API described in
[docs/api/frontend-contract.md](../docs/api/frontend-contract.md); every business rule stays in the
API.

## Run

Needs Node 22 and npm 10, and the API running (`make api`, port 8000).

```sh
make web-install   # once: npm --prefix web ci
make web           # dev server on http://localhost:5173
make web-test      # vitest + Testing Library
make web-build     # type-check and build to web/dist
```

The API base URL comes from `VITE_API_URL` (default `http://localhost:8000`). Set it in
`web/.env.local` or the shell, e.g. `VITE_API_URL=http://localhost:8000`. The API must allow the
web origin in `WEB_ORIGINS` (CORS).

## Layout

```
src/
  api/          client.ts (fetch, bearer token, 401 → session ended), endpoints.ts, types.ts
  auth/         session.tsx (token in memory + sessionStorage, /me, sign in/out)
  components/   AppShell (top bar + role nav), StageStepper, badges, ui primitives
  pages/        Login, Orders, OrderDetail, ReportProblem, Cases, Case, Approvals, ApprovalDetail, Help
  lib/          money (paise → ₹), format, stages (display only), roles (nav), useApi, usePolling
  manual/       bundles ../docs/manual/*.md (?raw) and renders them with marked + DOMPurify
  test/         setup and helpers (mockFetch, renderApp)
```

Fields the contract marks NEW are optional in `types.ts`; the UI hides what's missing (no
timeline → stepper only; no demo-accounts endpoint → no demo panel; no businesses endpoint → a
business ID text field).
