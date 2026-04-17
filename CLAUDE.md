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

## Running the full stack locally

```bash
# 1. Start all services (DynamoDB Local, MCP server, API, Vite dev server)
#    Add --seed to also seed demo data automatically once the API is ready
uv run inv dev [--seed]
```

`inv dev` sets automatically:

- `CORS_ORIGINS` — `localhost:5173` through `localhost:5179` (handles port
  collisions if 5173 is already taken by another project)
- `HIVE_VECTORS_BUCKET=local-dev` — prevents VectorStore from crashing on
  every list-memories request (semantic search will still fail locally)
- `HIVE_BYPASS_GOOGLE_AUTH=1` — enables the `?test_email=` auth shortcut
  (only activates when that query param is present; normal browser flows
  are unaffected)

```bash
# 2. Seed DynamoDB with demo data (also creates the table) — if not using --seed
uv run inv seed
```

Must be re-run after every `inv dev` restart (DynamoDB Local is ephemeral).

### Running UI e2e tests locally

```bash
# Auto-detects the Vite port — no env vars to set manually
uv run inv e2e-local

# Run a specific test file
uv run inv e2e-local --tests tests/e2e/test_ui_e2e.py

# Repeat N times to check for flakiness
uv run inv e2e-local --n 5
```

`inv e2e-local` probes ports 5173–5179 for the Hive Vite dev server (via
`/auth/login?test_email=probe`) and passes the detected URL as `HIVE_UI_URL`.

Key local e2e gotchas:

- The Vite proxy handles `/auth`, `/api`, `/oauth`, `/mcp` — tests must use
  the Vite URL (not the API URL directly) so the auth bypass sets
  `localStorage` at the correct origin.
- If Vite lands on a port other than 5173, `CORS_ORIGINS` must include that
  port. `inv dev` covers 5173–5179; if you're outside that range, pass
  `CORS_ORIGINS=http://localhost:<port>` when starting the stack.
- `inv seed` (or `inv dev --seed`) must succeed before running e2e tests —
  if auth bypass returns 500, the table is likely missing.
- `test_docs_e2e.py` is excluded automatically — those tests require a
  deployed VitePress build; run them against the deployed stack with `inv e2e`.

### When to run local e2e tests

Not required on every PR — `uv run inv pre-push` (unit + frontend tests) is
the standard gate. Run `inv e2e-local` before opening a PR when the change
touches any of the following:

**Always required:**

- Fixing a failing e2e test — the fix must pass locally before the PR opens
- Auth flows (`auth/`, `AuthCallback.jsx`, `LoginPage.jsx`, OAuth endpoints)
- MCP tool logic (`server.py`) — remember, recall, forget, search, list
- Management API endpoints (`api/`) that the UI or MCP tests exercise

**Use judgement (run the relevant `--tests` file at minimum):**

- UI component changes that affect user-visible flows (memory CRUD, client
  management, activity log)
- Vite proxy config or API base URL changes

**Not needed:**

- Pure unit test fixes, documentation, infra/CDK changes, style/CSS tweaks,
  or any change fully covered by unit + frontend tests

## Pre-PR checklist (required before every push)

Run `uv run inv pre-push` — this runs the same gate as CI:

1. `inv lint-backend` — ruff lint + format check
2. `inv typecheck` — mypy
3. `inv test-unit` — pytest unit tests
4. `inv test-frontend` — vitest

This is enforced automatically if you install the git hook:
`uv run inv install-hooks`

If infra files changed, also run: `uv run inv synth`

---

## Autonomous issue workflow

This section governs how Claude Code operates when given a batch of issues
to work through unattended.

### Core principle

Work autonomously. Do not ask for confirmation unless the situation is
explicitly listed under **Stop and ask** below. Make reasonable judgment
calls and document them in the PR description.

### Issue cycle

When given one or more GitHub issue numbers, process them **sequentially**.
Complete the full cycle for each issue before starting the next.

When given no specific issue number, use the selection algorithm in §0 to
pick the next one from the queue.

When processing a batch of issues, after completing each issue cycle
successfully, append the issue number to `.autonomous-progress` in the
repo root. This allows an interrupted batch to be resumed by checking
which issues are already recorded there.

#### 0. Pick the next issue (if none was given)

Every open issue should carry three metadata labels:

- **Status** — `status:ready`, `status:blocked`, `status:design-needed`,
  or `status:needs-info`
- **Priority** — `priority:p0` (ship this week) through `priority:p3`
  (someday-maybe)
- **Size** — `size:xs` (<1h), `size:s` (half-day), `size:m` (1–2 days),
  `size:l` (3–5 days), `size:xl` (epic; break down before picking up)

Pick the next issue using this deterministic queue:

1. **Filter** to issues matching ALL of:
   - `state:open`
   - `status:ready` (exclude `status:blocked`, `status:design-needed`,
     `status:needs-info`)
   - no assignee (not already being worked on)
   - not labelled `epic` (those are tracking issues, not implementation work)

2. **Sort** by priority descending: `p0` > `p1` > `p2` > `p3`.
   Missing priority label → treat as `p3`.

3. **Break priority ties** by size ascending (smallest first):
   `xs` > `s` > `m` > `l` > `xl`. Missing size label → treat as `m`.

4. **Break remaining ties** by issue number ascending (oldest first).

Saved GitHub query for the top of the queue:

```
is:issue is:open no:assignee label:status:ready -label:epic
```

Sort the result by label priority manually (GitHub search doesn't sort by
label precedence).

**Never pick** issues labelled `status:design-needed` or `status:needs-info`.
If you believe one of those issues is actually ready, state the case in a
comment and ask for the label to be changed — do not proceed unilaterally.

**Never pick** `size:xl` issues. Ask the user to break them into smaller
issues first.

**Never pick** issues from the "Stop and ask" list below, even if labelled
`status:ready`.

#### 1. Understand the issue

```bash
gh issue view <number>
```

Read the issue fully. Before doing anything else, check it is still open
and has no existing PR:

```bash
gh issue view <number> --json state -q .state          # must be OPEN
gh pr list --search "issue-<number>" --state open      # must be empty
```

If the issue is closed or already has an open PR, skip it and move to the
next. If the issue is ambiguous, make a reasonable interpretation, document
it in the PR description, and proceed.

#### 2. Branch

Always branch off `origin/development`, never off another feature branch.
Name the branch to match the issue type:

```bash
git fetch origin

# bug fix
git checkout -b fix/issue-<number>-<short-slug> origin/development
# feature / enhancement
git checkout -b feat/issue-<number>-<short-slug> origin/development
# chore / docs / refactor
git checkout -b chore/issue-<number>-<short-slug> origin/development
```

#### 3. Implement

Make the necessary changes. Follow all conventions in this file.

**Coverage:** 100% is required — CI fails below this.
- Every new Python module needs tests in `tests/unit/` or `tests/integration/`.
- Every new UI component needs a co-located `*.test.jsx` file.

**Copyright, UI conventions, dependency management:** follow the rules
defined in the sections above.

#### 4. Run pre-push gate

```bash
uv run inv pre-push
```

If infra files changed, also run:

```bash
uv run inv synth
```

Fix all failures before proceeding. Do not open a PR with a failing
pre-push gate.

#### 5. Run local e2e if warranted

Apply the "when to run local e2e tests" rules above to decide whether to
run e2e before opening the PR.

**Important:** `inv dev` is a long-lived blocking process. Do not attempt
to start it in the background during an autonomous session. Instead:

- If the local stack is already running (started externally), run:

  ```bash
  uv run inv e2e-local
  # or for a specific test file:
  uv run inv e2e-local --tests tests/e2e/<relevant_file>.py
  ```

- If the local stack is **not** running, skip local e2e and note in the PR
  description: *"Local e2e not run — CI will cover this on the development
  branch deploy."* The `development` pipeline deploys and runs the full e2e
  suite, which is an adequate safety net for most changes.

Fix any failures before proceeding.

**Decision rules for "use judgement" cases:**

- Any change to a UI component → run `tests/e2e/test_ui_e2e.py`
- Any change to `api/` endpoints → run `tests/e2e/test_mcp_e2e.py` and/or
  `tests/e2e/test_auth_e2e.py` depending on what's affected

#### 6. Create PR

Rebase and verify clean history:

```bash
git fetch origin
git rebase origin/development
git log --oneline origin/development..HEAD   # must show ONLY your commits
```

Push — use `-u` for a brand-new branch, `--force-with-lease` after a rebase
on an already-pushed branch:

```bash
# first push of this branch
git push -u origin <branch>

# after a rebase on a branch already pushed
git push --force-with-lease
```

Create the PR and enable squash auto-merge immediately:

```bash
gh pr create --base development \
  --title "<concise title>" \
  --body "Closes #<number>

## Summary
<what was changed and why>

## Approach
<any non-obvious decisions or interpretations of the issue>"

gh pr merge --auto --squash --delete-branch
```

#### 7. Monitor PR CI

Get the run ID and watch until all checks pass or a failure requires a fix:

```bash
gh run list --branch <branch> --limit 1   # get the run ID
gh run watch <run-id>
```

If any check fails:
1. Read the failure: `gh run view <run-id> --log-failed`
2. Fix on the same branch
3. `git push`
4. Get the new run ID: `gh run list --branch <branch> --limit 1`
5. Return to watching

Repeat until all checks pass. Auto-merge fires automatically once they do.

If the same check fails 3 times without a clear fix, stop and ask.

#### 8. Monitor development branch CI/CD post-merge

After the PR merges, the `development` branch pipeline triggers. Record the
merge time and poll until a matching run appears, then watch it:

```bash
# Record merge time, then poll until an active run created after merge appears
MERGE_TIME=$(date -u +%s)
while true; do
  RUN_ID=$(gh run list --branch development --limit 5 \
    --json databaseId,status,createdAt | \
    jq -r --argjson since "$MERGE_TIME" \
    '.[] | select(
        (.status == "in_progress" or .status == "queued") and
        (.createdAt | fromdateiso8601) > $since
      ) | .databaseId' | head -1)
  [ -n "$RUN_ID" ] && break
  sleep 15
done
gh run watch "$RUN_ID"
```

This uses `jq`'s built-in `fromdateiso8601` for portable timestamp parsing —
avoids the `date -r` vs `date -d` incompatibility between macOS and Linux,
and ensures we only latch onto a run triggered by this merge rather than a
pre-existing in-flight run from a concurrent PR.

If the pipeline fails:
1. Read the failure: `gh run view <run-id> --log-failed`
2. Create a new fix branch off the updated `origin/development`
3. Fix, run `inv pre-push`, run local e2e if warranted
4. PR and repeat from step 6

Only move to the next issue when the `development` pipeline is green.

### Keeping CLAUDE.md current

If you discover that CLAUDE.md is missing information needed to work
effectively — a new inv task, an undocumented gotcha, a test convention —
update it in the same PR as the change that surfaced it.

**Permitted without asking:**
- Adding or correcting inv task names, commands, or flags
- Documenting a newly discovered gotcha or test convention
- Updating the file structure map when new files are added

**Requires human review (open a separate PR, do not auto-merge):**
- Any change to the "Autonomous issue workflow" section
- Any change to the "Stop and ask" list
- Any change that expands what Claude is permitted to do unattended

### Stop and ask

When stopping, always emit a sentinel as the first line of your message:

```
HUMAN_INPUT_REQUIRED: <brief reason>
```

This allows automated monitoring to detect the stop and alert the operator.

Halt and wait for human input **only** in these situations:

- The PR is not auto-merging after CI passes and the reason is unclear
- The `development` pipeline failure is in infrastructure (CDK / Lambda /
  DynamoDB) and the root cause is not apparent from logs
- A change requires modifying `infra/stacks/hive_stack.py` in a way that
  could affect production resources
- The same CI check has failed 3 times without a clear fix

In all other cases, make a judgment call and proceed.

### What you must never do

- Push directly to `development` or `main`
- Merge a PR manually — auto-merge handles this
- Run `gh release create` — CI owns releases
- Hardcode credentials, secrets, or AWS account IDs
- Use `pip` or `requirements.txt` — always use `uv`
- Skip `inv pre-push` before creating a PR
- Pin GitHub Actions to mutable version tags — use full commit SHAs