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
│   │   ├── App.jsx
│   │   └── components/
│   │       ├── MemoryBrowser.jsx
│   │       ├── ClientManager.jsx
│   │       └── ActivityLog.jsx
│   └── package.json
├── infra/
│   ├── app.py                 # CDK app entry point
│   └── stacks/
│       └── hive_stack.py      # Lambda + DynamoDB + Function URLs + IAM
├── tests/
│   ├── unit/                  # Pure logic, no AWS deps
│   │   ├── test_models.py
│   │   ├── test_auth.py
│   │   └── test_storage.py
│   ├── integration/           # Tests against local DynamoDB
│   │   ├── test_mcp_tools.py
│   │   ├── test_api.py
│   │   └── test_oauth.py
│   └── e2e/                   # Tests against deployed AWS environment
│       ├── test_mcp_e2e.py
│       ├── test_auth_e2e.py
│       └── test_ui_e2e.py     # Playwright
├── .github/
│   └── workflows/
│       ├── ci.yml             # Run all tests on PR
│       └── deploy.yml         # Deploy to AWS on merge to main
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

## Testing
- pytest for all Python tests (unit, integration, e2e)
- DynamoDB Local (Docker) for integration tests
- Playwright for UI e2e tests
- Unit tests: no AWS deps, fully mocked
- Integration tests: run against DynamoDB Local
- E2e tests: run against deployed AWS staging environment

## CI/CD (GitHub Actions)
- ci.yml triggers on all PRs:
  - Lint (ruff) + type check (mypy)
  - Unit tests
  - Integration tests (spin up DynamoDB Local via Docker)
  - Frontend tests (vitest) + build
- deploy.yml triggers on merge to main:
  - Run full test suite
  - CDK deploy to AWS
  - Run e2e tests against deployed environment
  - Playwright e2e against deployed UI

## Conventions
- Use uv for all dependency management — never pip or requirements.txt
- MCP server on port 8000, management API on port 8001, UI on port 5173
- All infra in CDK (Python) under infra/
- All config via environment variables
- Never hardcode credentials or secrets
- AWS credentials in GitHub Actions via OIDC (no long-lived access keys)
