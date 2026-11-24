# Back-office (admin-ui-v2), phase 1

Read-only admin pages: dashboard, user list (search, role filter, sort, paging) and user detail.
Only accounts with the `admin` role can sign in here. Prompts and outputs are never shown.

## Run

```powershell
# 1) API (fake model, fresh data dir, one admin). Run from backend/.
$env:E2E_PASSWORD = "choose-a-test-password-here"
python scripts/e2e_server.py          # listens on 127.0.0.1:8011

# 2) Back-office dev server, from admin-ui-v2/. Proxies /api to the API above.
$env:API_TARGET = "http://127.0.0.1:8011"
npm install
npm run dev                            # http://127.0.0.1:5174
```

Sign in as `e2e-admin` with the password you set. The e2e script uses a fresh temp data dir each run,
so it is for local demos only, never for a real deployment.

## Checks

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```

## Not in phase 1

- Role or status changes, audit log, forgot password (see the design proposal, phases 2 and 3).
- Playwright E2E for these pages (unit tests cover the helpers only).
- Docker or nginx wiring; the build output is `dist/` and is not served by the existing stack yet.
- Light theme QA: the light palette is defined in tokens but its contrast was not measured with a tool.

## Design

Tokens live in `src/styles/pixel-tokens.css`. Components use only those tokens. Dark is the default;
light applies with `data-theme="light"`. Animation is off by default; set `data-motion="on"` on `<html>` to opt in.
