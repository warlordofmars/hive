# MCP tools overview

Hive exposes six tools that your AI agent can call during a conversation. You don't invoke these directly — your agent decides when to use them based on your instructions.

## Tool summary

| Tool | What it does |
| --- | --- |
| [`remember`](/tools/remember) | Store or update a memory |
| [`recall`](/tools/recall) | Retrieve a memory by its key |
| [`forget`](/tools/forget) | Delete a memory by its key |
| [`list_memories`](/tools/list-memories) | List all memories with a given tag |
| [`search_memories`](/tools/search-memories) | Search memories by semantic similarity |
| [`summarize_context`](/tools/summarize-context) | Summarise all memories on a topic |

## Scopes

Each OAuth token has one or both of the following scopes:

| Scope | Grants access to |
| --- | --- |
| `memories:read` | `recall`, `list_memories`, `search_memories`, `summarize_context` |
| `memories:write` | `remember`, `forget` |

Tokens issued through the standard OAuth flow get both scopes by default.

## How your agent uses the tools

You typically don't need to tell your agent which tool to use — just give natural language instructions:

- *"Remember that..."* → `remember`
- *"What did we decide about...?"* → `recall` or `search_memories`
- *"List everything tagged..."* → `list_memories`
- *"Forget the..."* → `forget`
- *"Give me a summary of..."* → `summarize_context`
