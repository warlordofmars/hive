# Connect your MCP client

Hive works with any MCP-compatible client. OAuth is handled automatically on first use — you don't need to generate or manage tokens manually.

## Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "hive": {
      "type": "http",
      "url": "https://hive.warlordofmars.net/mcp"
    }
  }
}
```

The next time you use a Hive memory tool in Claude Code, it will prompt you to authorise access via your browser. Complete the flow and you're connected.

## Cursor

Add to `~/.cursor/mcp.json` (create it if it doesn't exist):

```json
{
  "mcpServers": {
    "hive": {
      "type": "http",
      "url": "https://hive.warlordofmars.net/mcp"
    }
  }
}
```

Restart Cursor. On first use it will open a browser window to complete the OAuth flow.

## Claude Desktop

Claude Desktop requires [mcp-remote](https://github.com/geelen/mcp-remote) as a local proxy. `npx` will install it automatically.

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hive": {
      "command": "npx",
      "args": ["mcp-remote", "https://hive.warlordofmars.net/mcp"]
    }
  }
}
```

Restart Claude Desktop. On first use it will open a browser window to complete the OAuth flow.

## Continue (VS Code / JetBrains)

Add to your Continue config (`~/.continue/config.yaml`):

```yaml
mcpServers:
  - name: hive
    command: npx
    args:
      - mcp-remote
      - https://hive.warlordofmars.net/mcp
```

## claude.ai (web)

Go to **Settings → Integrations → Add MCP server** and enter:

```
https://hive.warlordofmars.net/mcp
```

## Multiple clients

You can connect multiple clients (Claude Code on your laptop, Cursor on another machine, claude.ai in the browser) simultaneously. Each client gets its own OAuth token, but they all share the same memory space under your account.

To manage or revoke individual clients, use the [OAuth clients](/ui-guide/oauth-clients) section of the management UI.

## Token refresh

Tokens expire after 1 hour and refresh automatically in Claude Code, Claude Desktop, and claude.ai. If a token expires in a client that doesn't auto-refresh, simply re-authorise by using a Hive tool — it will prompt you to complete the OAuth flow again.
