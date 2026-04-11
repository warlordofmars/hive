# Hive

A shared persistent memory MCP server for AI agents and teams.
Built with FastMCP (Python), AWS-native storage, and a React management UI.

## Stack

- FastMCP (Python) — MCP server + tool definitions
- FastAPI (Python) — OAuth 2.1 authorization server + management REST API
- React (Vite) + shadcn/ui — management UI SPA
- DynamoDB — persistent storage (single table design)
- AWS Lambda + Function URL — hosting for MCP server and API
- AWS CDK (Python) — IaC
- IAM roles — Lambda <-> DynamoDB auth
- Google OAuth — identity provider for management UI login
- GA4 (Google Analytics 4) — page view + event tracking on marketing site
- uv — dependency management (pyproject.toml + uv.lock)

## Structure

```text
hive/
├── src/
│   └── hive/
│       ├── server.py          # FastMCP server + tool definitions
│       ├── storage.py         # DynamoDB read/write logic
│       ├── models.py          # Memory + client + user data models
│       ├── logging_config.py  # Structured JSON logging setup
│       ├── metrics.py         # CloudWatch EMF metrics helpers
│       ├── vector_store.py    # S3 Vectors integration for semantic search
│       ├── auth/
│       │   ├── oauth.py       # OAuth 2.1 authorization server
│       │   ├── dcr.py         # Dynamic Client Registration (RFC 7591)
│       │   ├── tokens.py      # Token issuance + validation
│       │   ├── google.py      # Google OAuth integration
│       │   └── mgmt_auth.py   # Management API authentication
│       └── api/
│           ├── main.py        # FastAPI app + routes
│           ├── memories.py    # Memory CRUD endpoints
│           ├── clients.py     # OAuth client management endpoints
│           ├── stats.py       # Usage stats + activity log endpoints
│           ├── admin.py       # Admin-only endpoints
│           └── users.py       # User management endpoints
├── ui/
│   ├── src/
│   │   ├── App.jsx            # Router, AppShell, tab nav
│   │   ├── api.js             # API client (fetch wrappers)
│   │   ├── analytics.js       # GA4 trackPageView + trackEvent helpers
│   │   ├── hooks/
│   │   │   └── useTheme.js    # Dark/light theme hook
│   │   ├── lib/
│   │   │   └── utils.js       # Shared utility functions (cn, etc.)
│   │   └── components/
│   │       ├── ui/
│   │       │   └── button.jsx # shadcn/ui Button primitive
│   │       ├── MemoryBrowser.jsx
│   │       ├── ClientManager.jsx
│   │       ├── ActivityLog.jsx
│   │       ├── Dashboard.jsx  # Admin: CloudWatch metrics + cost data
│   │       ├── UsersPanel.jsx # Admin: user list + management
│   │       ├── SetupPanel.jsx # First-run MCP client setup wizard
│   │       ├── EmptyState.jsx # Shared empty-state illustrations
│   │       ├── PageLayout.jsx # Shared marketing page layout + navbar
│   │       ├── AuthCallback.jsx
│   │       ├── LoginPage.jsx
│   │       ├── HomePage.jsx   # Marketing landing page
│   │       ├── PricingPage.jsx
│   │       ├── FaqPage.jsx
│   │       ├── UseCasesPage.jsx
│   │       ├── McpClientsPage.jsx
│   │       ├── ChangelogPage.jsx
│   │       └── StatusPage.jsx
│   └── package.json
├── docs-site/                 # VitePress documentation site
│   ├── .vitepress/
│   │   ├── config.mjs         # base: "/docs/", nav, sidebar
│   │   └── theme/
│   │       ├── index.js       # Custom Layout (nav-bar-content-after slot)
│   │       └── style.css      # Dark navy navbar, brand colours
│   ├── getting-started/       # Quick start, connect client, first memory
│   ├── concepts/              # Memory scoping, tags, etc.
│   ├── tools/                 # Per-tool MCP reference pages
│   └── ui-guide/              # Management UI walkthrough
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
│       ├── test_admin_e2e.py  # Admin-only UI flows (Playwright)
│       ├── test_docs_e2e.py   # VitePress docs site (Playwright)
│       └── test_dashboard_e2e.py
├── scripts/
│   ├── check_copyright.py     # Copyright header linter
│   ├── seed_data.py           # Dev data seeding
│   └── synthetic_traffic.py   # Synthetic load for dev env
├── .github/
│   └── workflows/
│       ├── ci.yml             # CI on PRs + deploy on push to dev/main
│       ├── deploy-dev.yml     # Manual dev deploy (workflow_dispatch)
│       ├── security.yml       # Scheduled security scans
│       └── synthetic-traffic.yml  # Scheduled synthetic traffic
├── tasks.py                   # Invoke task definitions (lint, test, deploy)
├── pyproject.toml
└── README.md
```

## MCP Tools

- `remember(key, value, tags[])` — store a memory
- `recall(key)` — retrieve a memory by key
- `forget(key)` — delete a memory
- `list_memories(tag)` — list memories by tag
- `search_memories(query)` — semantic search across memories via S3 Vectors
- `summarize_context(topic)` — synthesize memories into a summary

## Auth

- OAuth 2.1 authorization server built into Hive (self-contained)
- Dynamic Client Registration per RFC 7591 (required by MCP spec)
- PKCE required on all authorization code flows
- Tokens stored in DynamoDB with TTL
- All MCP and API endpoints require a valid Bearer token
- Management UI login via Google OAuth (`/auth/login`)

## DynamoDB single table design

- Memory items: `PK=MEMORY#{memory_id}`, `SK=TAG#{tag}`
- OAuth client items: `PK=CLIENT#{client_id}`, `SK=META`
- Token items: `PK=TOKEN#{jti}`, `SK=META` (TTL enabled)
- Activity log items: `PK=LOG#{date}#{hour}`, `SK={timestamp}#{event_id}`
  (hour-sharded to avoid hot partitions)
- User items: `PK=USER#{user_id}`, `SK=META`
- Mgmt state items: `PK=MGMT_STATE#{state}`, `SK=META`
  (TTL enabled, used for OAuth state parameter)
- GSIs:
  - `TagIndex` — `GSI2PK=TAG#{tag}`, `GSI2SK=memory_id` (for list_memories)
  - `ClientIdIndex` — `GSI3PK=CLIENT#{client_id}` (for client lookups)
  - `UserEmailIndex` — `PK=EMAIL#{email}` (for user lookups by email)

## Management UI

- React SPA (Vite), runs on port 5173 in dev
- Communicates with FastAPI management API on port 8001
- Features:
  - Browse/search/create/edit/delete memories (`MemoryBrowser`)
  - Manage OAuth clients with DCR (`ClientManager`)
  - Activity log (`ActivityLog`)
  - First-run setup wizard (`SetupPanel`)
  - Admin only: user management (`UsersPanel`), metrics dashboard (`Dashboard`)
- Auth: Google OAuth via `/auth/login`;
  token stored in localStorage as `hive_mgmt_token`
- Tab set: Memories, OAuth Clients, Activity Log, Setup
  (+ Users, Dashboard for admins)

## Docs site

- VitePress with `base: "/docs/"` — served at `<domain>/docs/`
- CloudFront Function rewrites clean URLs (no extension → `.html`)
- Nav links injected via `nav-bar-content-after` layout slot as plain `<a>`
  elements (not Vue Router links) so Vue Router never intercepts
  marketing-site clicks
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
- **100% coverage required** — both Python (pytest-cov) and JS (vitest v8);
  CI fails below 100%
- Every new UI component needs a co-located `*.test.jsx` file

### E2e test conventions

- Use a unique tag per test run (e.g. `e2e-{timestamp}`) when creating test
  data, then filter by that tag to assert — avoids pagination issues from
  accumulated test data
- When selecting one element among many sharing a class, use Playwright
  `has_text=` (e.g. `page.locator(".docs-nav-link", has_text="Docs")`)
  to avoid strict-mode violations

## CI/CD (GitHub Actions)

`ci.yml` runs on every PR and push to `development` or `main`:

- Lint (ruff) + type check (mypy) + copyright headers
- Unit tests + integration tests (DynamoDB Local) + combined coverage report
- Frontend tests (vitest) + build; coverage uploaded to Codecov
- Docs site build
- Infra synth + Trivy IaC scan (CloudFormation SARIF → GitHub Security tab)
- Trivy dependency audit (SARIF → GitHub Security tab)
- SonarCloud scan
- On push to `development`: deploy to dev + run all e2e tests
- On push to `main`: release + deploy to prod + back-merge to development

Other workflows:

- `deploy-dev.yml` — manual dev deploy via `workflow_dispatch`
- `security.yml` — scheduled security scans
- `synthetic-traffic.yml` — scheduled synthetic load against dev environment

Deploy order: React SPA → docs site (docs depend on SPA deployment completing
first).

## Conventions

- Use uv for all dependency management — never pip or requirements.txt
- MCP server on port 8000, management API on port 8001, UI on port 5173
- All infra in CDK (Python) under `infra/`
- All config via environment variables
- Never hardcode credentials or secrets
- AWS credentials in GitHub Actions via OIDC (no long-lived access keys)
- Pin third-party GitHub Actions to full commit SHAs, not mutable version tags
  (e.g. `uses: actions/checkout@<sha> # v4`); use
  `gh api repos/{owner}/{repo}/git/ref/tags/{tag}` to resolve SHAs

## UI conventions

- **CSS variables only** — never hardcode colours; use `var(--text-muted)`,
  `var(--border)`, `var(--accent)`, `var(--danger)`, `var(--success)`, etc.
  for dark-mode compatibility
- **Lucide icons** — use `lucide-react` for all icons; never use emojis as
  UI elements
- **shadcn/ui primitives** — prefer shadcn components (Button, etc.) over
  custom HTML; add new primitives to `ui/src/components/ui/` as needed
- **jsdom colour normalisation** — in vitest, jsdom converts hex to
  `rgb(r, g, b)`; assert `"rgb(232, 160, 32)"` not `"#e8a020"`
- **Anonymous inline functions** — vitest v8 counts uncovered anonymous
  functions; extract or name handlers that must be tested (e.g. event
  listeners in `useEffect`)
- **`vi.useFakeTimers()`** — activate only *after* the initial async render
  completes (`await waitFor(...)`) otherwise fake timers block promise
  resolution

## Copyright headers

All source files must carry a copyright header. Current year is 2026.

New Python files:

```python
# Copyright (c) 2026 John Carter. All rights reserved.
```

New JS/JSX files:

```js
// Copyright (c) 2026 John Carter. All rights reserved.
```

When editing a file in a new year, append that year to the existing line
(e.g. editing in 2027 → `# Copyright (c) 2026, 2027 John Carter.
All rights reserved.`).

## PR workflow

### Opening a PR

1. Always branch off `origin/development`, never off another feature branch:

   ```bash
   git fetch origin
   git checkout -b fix/my-fix origin/development
   ```

2. Before `gh pr create`, rebase and verify clean history:

   ```bash
   git fetch origin
   git rebase origin/development
   git push --force-with-lease
   git log --oneline origin/development..HEAD  # must show ONLY your commits
   ```

3. Every PR body must include `Closes #NNN` linking to the GitHub issue.

4. Validate locally before pushing (same gate as CI):

   ```bash
   uv run inv pre-push        # lint + typecheck + unit tests + frontend tests
   uv run inv deploy --env jc # deploy to personal AWS env
   uv run inv e2e --env jc    # e2e tests against that env
   ```

5. After pushing, watch CI (`gh run watch`) and fix any failures immediately.

### Merge strategy

`gh pr create` doesn't support a merge-strategy flag — but immediately
enabling auto-merge after creating the PR pre-configures the strategy so
it fires automatically once CI passes:

```bash
# feature/fix → development  (squash)
gh pr create --base development ...
gh pr merge --auto --squash --delete-branch

# development → main  (merge commit)
gh pr create --base main ...
gh pr merge --auto --merge
```

| PR direction | Strategy | Why |
| --- | --- | --- |
| feature/fix → `development` | **Squash** | One clean commit per feature |
| `development` → `main` | **Merge commit** | Preserves squashed history |
| `main` → `development` (back-merge) | **Merge commit** | Handled by CI automatically |

### Releasing to production

1. **Create a release branch off `development`:**

   ```bash
   git fetch origin
   git checkout -b release/vX.Y.Z origin/development
   ```

2. **Update `CHANGELOG.md`** — move items from `[Unreleased]` to a new
   versioned section, e.g. `## [X.Y.Z] - 2026-04-11`.
   Commit the change:

   ```bash
   git add CHANGELOG.md
   git commit -m "chore: prepare release vX.Y.Z"
   git push -u origin release/vX.Y.Z
   ```

3. **Open a PR** from `release/vX.Y.Z` → `main`:

   ```bash
   gh pr create --base main --title "release: vX.Y.Z" \
     --body "Release vX.Y.Z. See CHANGELOG for details."
   ```

4. **Merge with `--merge`** (not squash) once CI passes:

   ```bash
   gh pr merge NNN --merge --delete-branch
   ```

5. **CI takes over** — on merge to `main`, the pipeline automatically:
   - Creates the GitHub release + tag
   - Deploys to prod
   - Back-merges `main` → `development`

   **Never run `gh release create` manually** — the pipeline owns this.

## Pre-PR checklist (required before every push)

Run `uv run inv pre-push` — this runs the same gate as CI:

1. `inv lint-backend` — ruff lint + format check
2. `inv typecheck` — mypy
3. `inv test-unit` — pytest unit tests
4. `inv test-frontend` — vitest

This is enforced automatically if you install the git hook:
`uv run inv install-hooks`

If infra files changed, also run: `uv run inv synth`
