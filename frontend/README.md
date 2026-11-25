# JobOrbit dashboard (Next.js)

The JobOrbit workspace: dashboard, job discovery, bulk preparation, auto-apply, tracking,
analytics and the rest, over the existing FastAPI backend. The backend stays the source of
truth; this app only reads and writes through its API.

## Run it

You need the backend running first (see the main [README](../README.md)).

```bash
cd frontend
npm install
cp .env.example .env.local      # adjust JOBORBIT_API_URL if the API is not on :8000
npm run dev                      # http://localhost:3000
```

Production build: `npm run build && npm run start`.

| Variable | Default | Meaning |
|---|---|---|
| `JOBORBIT_API_URL` | `http://127.0.0.1:8000` | Where the FastAPI backend listens |
| `JOBORBIT_API_TOKEN` | empty | Bearer token, only if the backend sets `JA_API_TOKEN` |

Both are read by the Next.js server only. The browser calls `/api/backend/...` and the route
handler in `src/app/api/backend/[...path]/route.ts` forwards to the backend, adding the
token server-side. So the backend needs no CORS change and the token never reaches the
browser. Only the backend's `/api/*` and `/health` paths are forwarded.

## Structure

```
src/
  app/
    layout.tsx                 fonts, theme pre-paint script, providers
    (workspace)/               every page, wrapped in the app shell
      dashboard/ jobs/ saved/ bulk/ auto-apply/ applications/ action-inbox/
      review-queue/ profile/ company-research/ interview-prep/ analytics/
      email/ sources/ logs/ settings/
    api/backend/[...path]/     same-origin proxy to FastAPI
  components/
    layout/                    sidebar, top bar, command palette, notification center
    navigation/ brand/         nav links, logo and orbital backdrop
    shared/                    PageHeader, Surface, KpiCard, ScoreRing, StatusBadge,
                               DataTable, EmptyState, ErrorState, AnimatedNumber
    dashboard/ jobs/ bulk/ auto-apply/ applications/ inbox/ profile/ research/
    email/ analytics/ sources/ logs/ settings/
    ui/                        shadcn/ui (Radix) primitives
  hooks/                       useTheme, useHealth, useNavCounts
  lib/
    api/                       client (errors), endpoints (one function per route), types
    constants/                 navigation, state labels and tones, theme key
    formatting/                dates, numbers, salary, experience
  types/api.d.ts               generated from the FastAPI OpenAPI schema
```

After a backend schema change, regenerate the types: `./scripts/generate-api-types.sh`.
A mismatch then shows up as a TypeScript error rather than a blank screen.

## Design system

All colours, surfaces, shadows, radius, motion and layout sizes are CSS variables in
`src/app/globals.css`, mapped to Tailwind names (`bg-surface-2`, `text-text-2`,
`text-violet`, `bg-success-soft`, `shadow-glow`, `font-heading`...). Components use those
names, never raw colours, so the dark (default) and light themes stay consistent. The
theme is applied before first paint by an inline script, so there is no flash.

Motion is subtle and respects `prefers-reduced-motion`.

## Data rules the UI keeps

- Nothing is invented: no sample data, no made-up trends, no counts without an endpoint.
  Missing data shows as "—", not 0.
- A prepared application is never shown as submitted; an auto-apply attempt is not a
  confirmation. Only the employer's acknowledgement counts as sent.
- Backend errors are shown verbatim, so the reason ("The emergency stop is on…") reaches
  you.

## Checks

```bash
npx tsc --noEmit
npm run lint
npm run build
```
