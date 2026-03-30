# Connecting to Hive via MCP

Hive exposes a standard MCP server over Streamable HTTP. Any MCP-compatible client can connect to it with a Bearer token.

## Prerequisites

You need two things before connecting:

1. **MCP URL** — the URL of your Hive MCP Lambda (ends in `/mcp`)
2. **Access token** — a valid OAuth Bearer token

### Getting an access token

Tokens are issued via the OAuth 2.1 authorization code flow (PKCE required). The easiest way to get one is through the [Admin UI](admin-ui.md#getting-a-token). Alternatively, use the CLI flow below.

#### CLI token issuance

```bash
# 1. Register a client
curl -s -X POST https://<api-url>/oauth/register \
  -H "Content-Type: application/json" \
  -d '{"client_name": "My Agent", "redirect_uris": ["http://localhost/cb"]}' \
  | jq .

# Save client_id from the response

# 2. Generate PKCE verifier + challenge
VERIFIER=$(python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())")
CHALLENGE=$(python3 -c "import base64,hashlib,sys; v=sys.argv[1].encode(); print(base64.urlsafe_b64encode(hashlib.sha256(v).digest()).rstrip(b'=').decode())" "$VERIFIER")

# 3. Get authorization code
curl -s -G https://<api-url>/oauth/authorize \
  --data-urlencode "response_type=code" \
  --data-urlencode "client_id=<client-id>" \
  --data-urlencode "redirect_uri=http://localhost/cb" \
  --data-urlencode "code_challenge=$CHALLENGE" \
  --data-urlencode "code_challenge_method=S256" \
  -D - | grep location

# Extract `code` from the redirect URL

# 4. Exchange code for token
curl -s -X POST https://<api-url>/oauth/token \
  -d "grant_type=authorization_code" \
  -d "code=<code>" \
  -d "redirect_uri=http://localhost/cb" \
  -d "client_id=<client-id>" \
  -d "code_verifier=$VERIFIER"
```

Tokens are valid for **1 hour**. Use the `refresh_token` from the response to get a new access token without re-authenticating.

---

## Claude Desktop

Add Hive to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hive": {
      "url": "https://<your-mcp-url>/mcp",
      "headers": {
        "Authorization": "Bearer <your-access-token>"
      }
    }
  }
}
```

Restart Claude Desktop. You should see "hive" appear in the MCP servers list with five tools: `remember`, `recall`, `forget`, `list_memories`, `summarize_context`.

---

## claude.ai (web)

In your claude.ai account settings, navigate to **Integrations → Add MCP server**:

- **Name:** Hive
- **URL:** `https://<your-mcp-url>/mcp`
- **Auth header:** `Authorization: Bearer <your-access-token>`

---

## Claude SDK / custom agents

```python
import anthropic

client = anthropic.Anthropic()

response = client.beta.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    mcp_servers=[
        {
            "type": "url",
            "url": "https://<your-mcp-url>/mcp",
            "name": "hive",
            "authorization_token": "<your-access-token>",
        }
    ],
    messages=[{"role": "user", "content": "Remember that the project deadline is March 31."}],
    betas=["mcp-client-2025-04-04"],
)
```

---

## Available MCP tools

Once connected, Claude has access to these tools:

| Tool | Description | Parameters |
|---|---|---|
| `remember` | Store or update a memory | `key` (str), `value` (str), `tags` (list[str]) |
| `recall` | Retrieve a memory by key | `key` (str) |
| `forget` | Delete a memory | `key` (str) |
| `list_memories` | List all memories with a given tag | `tag` (str) |
| `summarize_context` | Synthesize memories on a topic into a summary | `topic` (str) |

### Usage examples

```
User: Remember that our API rate limit is 1000 req/min.

Claude: [calls remember(key="api-rate-limit", value="1000 req/min", tags=["api", "limits"])]
        Stored memory 'api-rate-limit'.

User: What's our API rate limit?

Claude: [calls recall(key="api-rate-limit")]
        Your API rate limit is 1000 req/min.

User: Summarize everything we know about our API.

Claude: [calls summarize_context(topic="api")]
        ## Memories tagged 'api'
        **api-rate-limit**: 1000 req/min
        ...
```

---

## Shared memory across agents

Because all agents connect to the same Hive instance, memories stored by one agent are immediately available to others. Use tags to namespace memories by team, project, or topic:

```
remember(key="team/alice/current-task", value="...", tags=["team", "alice"])
remember(key="project/hive/status", value="...", tags=["project", "hive"])
list_memories(tag="project")  # → all project memories across all agents
```

---

## Token management

- Tokens expire after **1 hour**
- Each OAuth client gets its own tokens — revoke one client without affecting others
- To refresh: `POST /oauth/token` with `grant_type=refresh_token&refresh_token=<token>`
- To revoke: `POST /oauth/revoke` with `token=<token>`
- Manage clients via the [Admin UI](admin-ui.md) or the [API](api-reference.md#clients)
