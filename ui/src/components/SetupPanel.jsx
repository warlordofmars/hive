// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useState } from "react";

export default function SetupPanel() {
  const mcpUrl = import.meta.env.VITE_MCP_BASE ?? `${window.location.origin}/mcp`;
  const [activeTab, setActiveTab] = useState("code");
  const [copied, setCopied] = useState(false);

  const httpConfig = JSON.stringify(
    { mcpServers: { hive: { type: "http", url: mcpUrl } } },
    null,
    2,
  );
  const mrConfig = JSON.stringify(
    { mcpServers: { hive: { command: "npx", args: ["mcp-remote", mcpUrl] } } },
    null,
    2,
  );
  const configs = {
    code: httpConfig,
    cursor: httpConfig,
    desktop: mrConfig,
  };

  function handleCopy() {
    navigator.clipboard.writeText(configs[activeTab]);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const tabStyle = (tab) => ({
    padding: "6px 16px",
    border: "1px solid var(--border)",
    borderBottom: activeTab === tab ? "1px solid var(--bg)" : "1px solid var(--border)",
    borderRadius: "4px 4px 0 0",
    background: activeTab === tab ? "var(--bg)" : "var(--surface)",
    color: "var(--text)",
    cursor: "pointer",
    marginBottom: -1,
    fontWeight: activeTab === tab ? 600 : 400,
  });

  return (
    <div style={{ maxWidth: 640 }}>
      <h2 style={{ marginBottom: 24 }}>Set up Hive</h2>

      <section style={{ marginBottom: 32 }}>
        <h3 style={{ marginBottom: 12 }}>Step 1 — Connect your MCP client</h3>
        <p style={{ marginBottom: 12, color: "var(--text-muted)" }}>
          Add Hive to your client config. OAuth is handled automatically on first use — no token
          needed.
        </p>

        <div style={{ display: "flex", gap: 4, marginBottom: 0 }}>
          <button style={tabStyle("code")} onClick={() => setActiveTab("code")}>
            Claude Code
          </button>
          <button style={tabStyle("cursor")} onClick={() => setActiveTab("cursor")}>
            Cursor
          </button>
          <button style={tabStyle("desktop")} onClick={() => setActiveTab("desktop")}>
            Claude Desktop
          </button>
        </div>

        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: "0 4px 4px 4px",
            padding: "12px 16px",
            background: "var(--bg)",
          }}
        >
          {activeTab === "code" && (
            <p style={{ margin: "0 0 8px", color: "var(--text-muted)", fontSize: 13 }}>
              Add to <code>~/.claude/settings.json</code>:
            </p>
          )}
          {activeTab === "cursor" && (
            <p style={{ margin: "0 0 8px", color: "var(--text-muted)", fontSize: 13 }}>
              Add to <code>~/.cursor/mcp.json</code> (create it if it doesn't exist):
            </p>
          )}
          {activeTab === "desktop" && (
            <p style={{ margin: "0 0 8px", color: "var(--text-muted)", fontSize: 13 }}>
              Add to{" "}
              <code>~/Library/Application Support/Claude/claude_desktop_config.json</code>.
              Requires <a href="https://github.com/geelen/mcp-remote" target="_blank" rel="noreferrer">mcp-remote</a> (
              <code>npx</code> will install it automatically):
            </p>
          )}
          <pre
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              padding: "12px 16px",
              fontSize: 13,
              overflowX: "auto",
              margin: 0,
              color: "var(--text)",
            }}
          >
            {configs[activeTab]}
          </pre>
          <button className="secondary" onClick={handleCopy} style={{ marginTop: 8 }}>
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
      </section>

      <section>
        <h3 style={{ marginBottom: 12 }}>Step 2 — Authorise</h3>
        <p style={{ color: "var(--text-muted)" }}>
          {activeTab === "code"
            ? "Open Claude Code. The next time you use a Hive memory tool, it will prompt you to authorise access via your browser. Complete the flow and you're done."
            : activeTab === "cursor"
            ? "Restart Cursor. On first use it will open a browser window to complete the OAuth flow. After authorising, the connection is maintained automatically."
            : "Restart Claude Desktop. On first use it will open a browser window to complete the OAuth flow. After authorising, the connection is maintained automatically."}
        </p>
      </section>
    </div>
  );
}
