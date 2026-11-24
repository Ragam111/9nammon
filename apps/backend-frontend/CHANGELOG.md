# Changelog

Every file created, moved or deleted in this app is listed here (rule from the back-office brief).
Nothing has been deleted or moved yet.

## 2026-11-23 · V1 local free models (spec only)

### Added
- `V1_LOCAL_FREE.md`: v1 scope for free Ollama models, what already exists, what is out of scope (token packs,
  payments, customer API key), open decisions, and the known P6 minor items. No code changed.

### Not changed
- All backend and frontend code, `LOCAL_MODELS_ENABLED` default (still `false`), quota rules, and the schema.

## 2026-11-22 · Back-office phase 1 (read-only)

### Added
- `backend/app/admin.py`: read-only admin API under `/api/admin/*`. Every route requires the admin role
  (anonymous: 401, normal user: 403). Routes: `GET /api/admin/stats`, `GET /api/admin/users`
  (search, role filter, whitelisted sort and order, paging), `GET /api/admin/users/{id}`.
  No prompts or outputs are returned. No schema change.
- `backend/tests/test_admin.py`: role checks, list paging and search (wildcards are literal), no password
  hashes or prompt text in responses, detail 404, stats counts.
- `admin-ui-v2/`: separate Vite + React + TypeScript app for the back-office.
  - `package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`, `biome.json`, `index.html`, `.gitignore`, `README.md`
  - `src/main.tsx`, `src/App.tsx`: shell, session check (admin only), theme switch, navigation
  - `src/lib/api.ts`, `src/lib/format.ts`, `src/lib/format.test.ts`, `src/lib/router.ts`: fetch wrapper, Bangkok time, query builder, hash router
  - `src/styles/pixel-tokens.css`, `src/styles/pixel.css`: design tokens and pixel components (no Mojang assets)
  - `src/components/pixel/icons.tsx`, `src/components/pixel/primitives.tsx`: icons, bevel button, badge, state screen, slot table, block loader
  - `src/pages/Login.tsx`, `src/pages/Dashboard.tsx`, `src/pages/Users.tsx`, `src/pages/UserDetail.tsx`

### Changed
- `backend/app/main.py`: import `admin` and mount `admin.router` on the app (one import line, one include line).
- `backend/tests/test_security.py`: endpoint walker now covers every included router, so the admin routes
  are checked for auth too. Expected endpoint count 19 → 22 (3 admin routes).

- `.claude/launch.json` (repo root): two preview entries, `bf-admin-api` (e2e-style API on port 8011, a throwaway local password) and `bf-admin-ui` (Vite on 5174).

### Not changed
- `backend/app/db.py` (schema), `backend/.env`, `.env.example`, `docker-compose.yml`, `frontend/`, existing migrations and data.
