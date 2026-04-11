## Project: Hive
A shared persistent memory MCP server for Claude agents and teams.
Built with FastMCP (Python), AWS-native storage, and a React management UI.

## Stack
- FastMCP (Python) — MCP server + tool definitions
- FastAPI (Python) — OAuth 2.1 authorization server + management REST API
- React (Vite) — management UI SPA
- DynamoDB — persistent storage (single table design)
- AWS Lambda + Function URL — hosting for MCP server and API
- AWS CDK (Python) — IaC
- IAM roles — Lambda <-> DynamoDB auth
- uv — dependency management (pyproject.toml + uv.lock)

## Structure
hive/
├── src/
│   └── hive/
│       ├── server.py          # FastMCP server + tool definitions
│       ├── storage.py         # DynamoDB read/write logic
│       ├── models.py          # Memory + client data models
│       ├── auth/
│       │   ├── oauth.py       # OAuth 2.1 authorization server
│       │   ├── dcr.py         # Dynamic Client Registration (RFC 7591)
│       │   └── tokens.py      # Token issuance + validation
│       └── api/
│           ├── main.py        # FastAPI app + routes
│           ├── memories.py    # Memory CRUD endpoints
│           ├── clients.py     # OAuth client management endpoints
│           └── stats.py       # Usage stats + activity log endpoints
├── ui/
│   ├── src/
│   │   ├── App.jsx            # Router, AppShell, tab nav
│   │   ├── api.js             # API client (fetch wrappers)
│   │   └── components/
│   │       ├── MemoryBrowser.jsx
│   │       ├── ClientManager.jsx
│   │       ├── ActivityLog.jsx
│   │       ├── Dashboard.jsx
│   │       ├── UsersPanel.jsx
│   │       ├── SetupPanel.jsx
│   │       ├── EmptyState.jsx # Shared empty-state illustrations
│   │       ├── HomePage.jsx   # Marketing landing page
│   │       └── ...            # Other marketing pages
│   └── package.json
├── docs-site/                 # VitePress documentation site
│   ├── .vitepress/
│   │   ├── config.mjs         # base: "/docs/", nav, sidebar
│   │   └── theme/
│   │       ├── index.js       # Custom Layout (nav-bar-content-after slot)
│   │       └── style.css      # Dark navy navbar, brand colours
│   └── getting-started/       # Markdown content
├── infra/
│   ├── app.py                 # CDK app entry point
│   └── stacks/
│       └── hive_stack.py      # Lambda + DynamoDB + CloudFront + IAM
├── tests/
│   ├── unit/                  # Pure logic, no AWS deps
│   ├── integration/           # Tests against DynamoDB Local
│   └── e2e/                   # Playwright tests against deployed env
│       ├── test_mcp_e2e.py
│       ├── test_auth_e2e.py
│       ├── test_ui_e2e.py     # Admin UI (Playwright)
│       ├── test_docs_e2e.py   # VitePress docs site (Playwright)
│       └── test_dashboard_e2e.py
├── .github/
│   └── workflows/
│       ├── ci.yml             # CI on every PR + deploy to dev on push to development
│       └── deploy-dev.yml     # Manual dev deploy (workflow_dispatch)
├── pyproject.toml
└── README.md

## MCP Tools
- remember(key, value, tags[]) — store a memory
- recall(key) — retrieve a memory by key
- forget(key) — delete a memory
- list_memories(tag) — list memories by tag
- summarize_context(topic) — synthesize memories into a summary

## Auth
- OAuth 2.1 authorization server built into Hive (self-contained)
- Dynamic Client Registration per RFC 7591 (required by MCP spec)
- PKCE required on all authorization code flows
- Tokens stored in DynamoDB with TTL
- All MCP and API endpoints require a valid Bearer token

## DynamoDB single table design
- Memory items: PK=MEMORY#{memory_id}, SK=TAG#{tag}
- OAuth client items: PK=CLIENT#{client_id}, SK=META
- Token items: PK=TOKEN#{jti}, SK=META (TTL enabled)
- Activity log items: PK=LOG#{date}, SK={timestamp}#{event_id}
- GSI on tag for list_memories queries
- GSI on client_id for client lookups

## Management UI
- React SPA (Vite), runs on port 5173 in dev
- Communicates with FastAPI management API on port 8001
- Features: browse/search/create/edit/delete memories,
  manage OAuth clients (DCR), usage stats, activity log
- Auth: Google OAuth via `/auth/login`; token stored in localStorage as `hive_mgmt_token`

## Docs site
- VitePress with `base: "/docs/"` — served at `<domain>/docs/`
- CloudFront Function rewrites clean URLs (no extension → `.html`)
- Nav links injected via `nav-bar-content-after` layout slot as plain `<a>` elements
  (not Vue Router links) so Vue Router never intercepts marketing-site clicks
- Deployed to S3 prefix `docs/` alongside the React SPA in the same bucket
- `DeployUi` CDK construct uses `prune=False` — never delete docs assets
- `DeployDocs` depends on `DeployUi` so docs always win on final write order

## Testing

- pytest for all Python tests (unit, integration, e2e)
- DynamoDB Local (Docker) for integration tests
- Playwright for UI e2e tests
- Unit tests: no AWS deps, fully mocked
- Integration tests: run against DynamoDB Local
- E2e tests: run against deployed AWS dev environment
- **100% coverage required** — both Python (pytest-cov) and JS (vitest v8); CI fails below 100%
- Every new UI component needs a co-located `*.test.jsx` file

### E2e test conventions

- Use a unique tag per test run (e.g. `e2e-{timestamp}`) when creating test data, then
  filter by that tag to assert — avoids pagination issues from accumulated test data
- When selecting one element among many sharing a class, use Playwright `has_text=`
  (e.g. `page.locator(".docs-nav-link", has_text="Docs")`) to avoid strict-mode violations

## CI/CD (GitHub Actions)

- `ci.yml` runs on every PR and push to `development` or `main`:
  - Lint (ruff) + type check (mypy) + copyright headers
  - Unit tests, integration tests (DynamoDB Local), frontend tests (vitest) + build
  - Docs site build, infra synth + Trivy IaC scan
  - On push to `development`: deploy to dev + run all e2e tests
  - On push to `main`: release + deploy to prod + back-merge to development
- `deploy-dev.yml` — manual dev deploy via `workflow_dispatch`
- Deploy order: React SPA → docs site (docs depend on SPA deployment completing first)

## Conventions
- Use uv for all dependency management — never pip or requirements.txt
- MCP server on port 8000, management API on port 8001, UI on port 5173
- All infra in CDK (Python) under infra/
- All config via environment variables
- Never hardcode credentials or secrets
- AWS credentials in GitHub Actions via OIDC (no long-lived access keys)

## UI conventions

- **CSS variables only** — never hardcode colours; use `var(--text-muted)`, `var(--border)`,
  `var(--accent)`, `var(--danger)`, `var(--success)`, etc. for dark-mode compatibility
- **Lucide icons** — use `lucide-react` for all icons; never use emojis as UI elements
- **jsdom colour normalisation** — in vitest, jsdom converts hex to `rgb(r, g, b)`;
  assert `"rgb(232, 160, 32)"` not `"#e8a020"`
- **Anonymous inline functions** — vitest v8 counts uncovered anonymous functions;
  extract or name handlers that must be tested (e.g. event listeners in `useEffect`)
- **`vi.useFakeTimers()`** — activate only *after* the initial async render completes
  (`await waitFor(...)`) otherwise fake timers block promise resolution

## Pre-PR checklist (required before every push)

Run `uv run inv pre-push` — this runs the same gate as CI:

  1. `inv lint-backend`  — ruff lint + format check
  2. `inv typecheck`     — mypy
  3. `inv test-unit`     — pytest unit tests
  4. `inv test-frontend` — vitest
This is enforced automatically if you install the git hook: `uv run inv install-hooks`
If infra files changed, also run: `uv run inv synth`
