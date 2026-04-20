# MCP Resources

Alongside its [tools](/tools/overview) and [prompts](/tools/prompts), Hive exposes memories as **MCP Resources** — read-only, URI-addressable content that supporting clients can reference declaratively without a tool round-trip.

::: tip Tool vs Resource vs Prompt
- A **[Tool](/tools/overview)** is something the agent *calls*. It does work and returns a JSON response.
- A **Resource** is *content* the agent can read by URI. Clients can pre-fetch or cache it.
- A **[Prompt](/tools/prompts)** is a *template* the client surfaces as a slash command.
:::

## URI scheme

| URI | What it returns |
| --- | --- |
| `memory://index` | A newline-separated list of every `memory://{key}` URI the authenticated client owns |
| `memory://{key}` | The value of one specific memory |

All reads are scoped to the authenticated OAuth client (`client_id`) and require the `memories:read` scope. The token flows through the same `Authorization: Bearer <token>` header as the tools — nothing new to configure.

## Reading the index first

Resources are listed in two places:

- `resources/list` returns the concrete `memory://index` resource
- `resources/templates/list` returns the template `memory://{key}`

Clients typically read `memory://index` first to discover what's available:

```
memory://release/cadence
memory://release/back-merge
memory://release/smoke-tests
```

Then read a specific entry:

```
memory://release/cadence
→ "Weekly on Thursdays at 2pm UTC"
```

## Why resources, not just tools

- **Lower latency** — clients can cache resources and stream them into context without a round-trip through the model
- **Declarative referencing** — the agent can point at `memory://release/cadence` in a prompt instead of calling a tool and pasting the response
- **MCP primitive alignment** — using the full primitive set (tools, resources, prompts) lets Hive slot into any compliant client without custom client glue

## Tenant isolation

Resource reads enforce tenant isolation at the handler level:

- `memory://{key}` returns "not found" (not "forbidden") when the key belongs to another OAuth client, so the existence of another tenant's keys never leaks
- `memory://index` only enumerates memories owned by the authenticated client — other tenants' keys never appear

## Redacted memories

Memories that have been tombstoned via the `redact_memory` tool are excluded from the index and reject `memory://{key}` reads with an explicit "redacted" error. The error distinguishes a redacted memory from a missing one so client UIs can surface the right message.

## Truncation

`memory://index` caps at the first 500 URIs (sorted alphabetically). When truncation kicks in, the resource body ends with a note directing the agent to fall back to the [`list_memories`](/tools/list-memories) tool for narrower retrieval — tags are the right primitive for large corpora.

## Writes still go through tools

Resources are intentionally read-only. Storing, updating, and deleting memories continues to go through [`remember`](/tools/remember) / [`forget`](/tools/forget) plus the `redact_memory` tool (advertised via `tools/list` on supported clients). Centralising writes in one place keeps the quota, TTL, version, and audit-log machinery in a single code path.

## Client support

Resources only appear in clients that implement the MCP Resources capability:

- **Claude Code** — lists resources in the MCP panel
- **Claude Desktop** — shows resources under connected servers
- **Cursor** — lists resources in the MCP resources menu

Clients that don't support Resources can still reach every memory via the tool surface; nothing breaks.
