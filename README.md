# Hive

<!-- CI/CD & quality -->
[![CI (main)](https://github.com/warlordofmars/hive/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/warlordofmars/hive/actions/workflows/ci.yml?query=branch%3Amain)
[![CI (dev)](https://github.com/warlordofmars/hive/actions/workflows/ci.yml/badge.svg?branch=development)](https://github.com/warlordofmars/hive/actions/workflows/ci.yml?query=branch%3Adevelopment)
[![codecov](https://codecov.io/gh/warlordofmars/hive/branch/main/graph/badge.svg)](https://codecov.io/gh/warlordofmars/hive)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/type--checked-mypy-blue)](https://mypy-lang.org/)

<!-- Project & versioning -->
[![GitHub release](https://img.shields.io/github/v/release/warlordofmars/hive)](https://github.com/warlordofmars/hive/releases)
[![GitHub issues](https://img.shields.io/github/issues/warlordofmars/hive)](https://github.com/warlordofmars/hive/issues)
[![GitHub stars](https://img.shields.io/github/stars/warlordofmars/hive)](https://github.com/warlordofmars/hive/stargazers)

<!-- Backend stack -->
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.x-7B2FBE?logo=python&logoColor=white)](https://github.com/jlowin/fastmcp)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![AWS Lambda](https://img.shields.io/badge/AWS_Lambda-FF9900?logo=awslambda&logoColor=white)](https://aws.amazon.com/lambda/)
[![DynamoDB](https://img.shields.io/badge/DynamoDB-4053D6?logo=amazondynamodb&logoColor=white)](https://aws.amazon.com/dynamodb/)
[![AWS CDK](https://img.shields.io/badge/CDK-Python-FF9900?logo=amazonaws&logoColor=white)](https://aws.amazon.com/cdk/)

<!-- Frontend stack -->
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](https://reactjs.org/)
[![Vite](https://img.shields.io/badge/Vite-5.x-646CFF?logo=vite&logoColor=white)](https://vitejs.dev/)
[![Node](https://img.shields.io/badge/Node-20-339933?logo=nodedotjs&logoColor=white)](https://nodejs.org/)

<!-- MCP -->
[![MCP](https://img.shields.io/badge/MCP-compatible-blueviolet)](https://modelcontextprotocol.io/)

Shared persistent memory for Claude agents and teams. Hive is a self-hosted MCP server that lets any number of Claude agents store, retrieve, and share memories across conversations — backed by DynamoDB and secured with OAuth 2.1.

## What it does

Claude agents are stateless. Hive gives them a shared, durable memory store:

- **Remember** — store any key/value pair with optional tags
- **Recall** — retrieve a memory by key
- **Forget** — delete a memory
- **List** — enumerate memories by tag
- **Summarize** — synthesize all memories on a topic into a summary

Multiple agents or team members connect using their own OAuth client credentials, so you can track who stored what and revoke access individually.

## Architecture

```
Claude (MCP client)
      │  MCP / Streamable HTTP
      ▼
┌─────────────────┐     ┌──────────────────┐
│   MCP Lambda    │     │   API Lambda     │
│  (FastMCP)      │     │  (FastAPI)       │
│  /mcp endpoint  │     │  /api/*  /oauth/*│
└────────┬────────┘     └────────┬─────────┘
         │                       │
         └──────────┬────────────┘
                    ▼
             ┌─────────────┐
             │  DynamoDB   │
             │  (hive)     │
             └─────────────┘

         Browser
            │
            ▼
    ┌───────────────┐
    │  CloudFront   │  → S3 (React UI)
    │               │  → API Lambda (/api/*, /oauth/*)
    └───────────────┘
```

| Layer | Technology |
|---|---|
| MCP server | FastMCP 3.x (Python) |
| Auth server | OAuth 2.1 + PKCE built into the API Lambda |
| Management API | FastAPI (Python) |
| Management UI | React 18 + Vite |
| Storage | DynamoDB (single-table design) |
| Hosting | AWS Lambda Function URLs + CloudFront + S3 |
| IaC | AWS CDK (Python) |
| CI/CD | GitHub Actions + OIDC |

## Quick start

See [docs/mcp-setup.md](docs/mcp-setup.md) for step-by-step instructions on connecting Claude to your Hive instance.

**TL;DR for Claude Desktop:**

```json
{
  "mcpServers": {
    "hive": {
      "url": "https://<your-mcp-url>/mcp",
      "headers": {
        "Authorization": "Bearer <your-token>"
      }
    }
  }
}
```

## Project structure

```
hive/
├── src/hive/               # Python backend
│   ├── server.py           # FastMCP server + MCP tool definitions
│   ├── storage.py          # DynamoDB read/write
│   ├── models.py           # Pydantic data models
│   ├── auth/
│   │   ├── oauth.py        # OAuth 2.1 authorization server
│   │   ├── dcr.py          # Dynamic Client Registration (RFC 7591)
│   │   └── tokens.py       # JWT issuance + validation
│   └── api/
│       ├── main.py         # FastAPI app
│       ├── memories.py     # Memory CRUD endpoints
│       ├── clients.py      # OAuth client management
│       └── stats.py        # Usage stats + activity log
├── ui/                     # React management UI
├── infra/                  # AWS CDK infrastructure
├── tests/
│   ├── unit/               # No AWS deps, fully mocked
│   ├── integration/        # Against DynamoDB Local
│   └── e2e/                # Against deployed AWS environment
└── docs/                   # Additional documentation
```

## Documentation

| Doc | Description |
|---|---|
| [docs/mcp-setup.md](docs/mcp-setup.md) | Connecting Claude (Desktop, claude.ai, SDK) to Hive |
| [docs/admin-ui.md](docs/admin-ui.md) | Using the management UI |
| [docs/api-reference.md](docs/api-reference.md) | REST API reference |
| [docs/oauth.md](docs/oauth.md) | OAuth 2.1 implementation details |
| [src/hive/README.md](src/hive/README.md) | Backend package internals |
| [ui/README.md](ui/README.md) | Frontend development |
| [infra/README.md](infra/README.md) | Infrastructure and deployment |
| [tests/README.md](tests/README.md) | Running tests |

## Development setup

**Prerequisites:** Python 3.12+, Node 20+, Docker (for DynamoDB Local), [uv](https://docs.astral.sh/uv/)

```bash
# Clone and install
git clone https://github.com/warlordofmars/hive
cd hive
uv sync --all-extras

# Run the MCP server locally (stdio transport)
uv run python -m hive.server

# Run the management API locally
uv run uvicorn hive.api.main:app --port 8001 --reload

# Run the React UI
cd ui && npm install && npm run dev   # http://localhost:5173
```

## Running tests

```bash
# Unit tests (no dependencies)
uv run pytest tests/unit -v

# Integration tests (requires DynamoDB Local)
docker run -d -p 8000:8000 amazon/dynamodb-local
DYNAMODB_ENDPOINT=http://localhost:8000 \
AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=us-east-1 \
uv run pytest tests/integration -v

# E2E tests (requires deployed stack)
HIVE_API_URL=https://... HIVE_MCP_URL=https://... HIVE_UI_URL=https://... \
uv run pytest tests/e2e -v
```

See [tests/README.md](tests/README.md) for full details.

## Deployment

Hive deploys automatically to AWS on every push to `main` via GitHub Actions. See [infra/README.md](infra/README.md) for manual deployment and initial setup instructions.

## Cost monitoring

All AWS resources are tagged with `project=hive` and `env=<environment>` for cost allocation.

View costs in [AWS Cost Explorer](https://us-east-1.console.aws.amazon.com/cost-management/home#/cost-explorer) — filter by tag:

| Environment | Tag filter |
|---|---|
| Production | `env = prod` |
| Development | `env = dev` |
| All Hive | `project = hive` |

> **Note:** Tags must be activated in [Billing → Cost allocation tags](https://us-east-1.console.aws.amazon.com/billing/home#/tags) before they appear as filters in Cost Explorer. New tags can take up to 24 hours to propagate into billing data.
