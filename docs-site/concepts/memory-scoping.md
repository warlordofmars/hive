# How memory scoping works

Understanding how memories are scoped helps you predict what your agent can and can't see.

## The workspace model

Every memory lives in a **workspace**. When you first sign in, Hive creates a
Personal workspace for your account, and every memory your agents store lands
there by default.

```
Your account
├── Workspace: "you@example.com's Personal"
│   ├── memory: project/deadline
│   ├── memory: preferences/code-style
│   └── memory: ref/api-docs
└── Workspace: "Team Atlas"          (shared workspaces are rolling out)
    ├── memory: project/current-task
    └── memory: ref/db-schema
```

## Scope comes from the token

Every access token Hive issues carries a `workspace_id` claim. When an MCP
client registers (via Dynamic Client Registration) it is bound to a
workspace — either explicitly at registration time or automatically to your
Personal workspace when you sign in — and every token minted for that client
carries the binding.

Tool calls never take a workspace parameter. To operate in a different
workspace, an agent registers a client bound to that workspace and swaps
tokens.

## What each token sees

All MCP tools enforce the workspace boundary:

- `recall`, `forget`, `memory_history`, `restore_memory`, and the other
  key-addressed tools treat memories from another workspace as **not found**
  — even if you know the exact key.
- `remember` refuses to overwrite a key held by another workspace.
- `list_memories`, `list_tags`, `search_memories`, `summarize_context`, and
  `pack_context` only surface memories from the token's workspace — memories
  stored in one workspace never appear in another workspace's listings,
  tag sets, search results, or summaries.

Within a workspace, memories are shared across all of your connected MCP
clients: a memory stored by Claude Code is visible to Cursor as long as both
are bound to the same workspace.

## The management UI sees everything

When you browse memories in the management UI at
[hive.warlordofmars.net](https://hive.warlordofmars.net), you see all memories
across your account. You can browse, edit, and delete any of them regardless
of which client created them.

## Memories from before workspaces

Memories created before your account was migrated to the workspace model are
visible from any of your workspaces until the migration stamps them into your
Personal workspace. They remain private to your account either way.

## Team sharing

If multiple people use the same Hive instance, each account is isolated from
others. Admin users can see all memories across all accounts via the
management UI, but standard users only see their own.
