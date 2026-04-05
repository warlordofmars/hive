// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useState } from "react";
import { api } from "../api.js";

export default function SetupPanel() {
  const mcpUrl = import.meta.env.VITE_MCP_BASE ?? `${window.location.origin}/mcp`;
  const [clientName, setClientName] = useState("");
  const [clientId, setClientId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  async function handleRegister(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const data = await api.createClient({ client_name: clientName });
      setClientId(data.client_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const configSnippet = JSON.stringify(
    { mcpServers: { hive: { type: "http", url: mcpUrl } } },
    null,
    2,
  );

  function handleCopy() {
    navigator.clipboard.writeText(configSnippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div style={{ maxWidth: 640 }}>
      <h2 style={{ marginBottom: 24 }}>Set up Hive</h2>

      <section style={{ marginBottom: 32 }}>
        <h3 style={{ marginBottom: 12 }}>Step 1 — Register a client</h3>
        <p style={{ marginBottom: 12, color: "#555" }}>
          Give your MCP client a name (e.g. &ldquo;Claude Code&rdquo; or &ldquo;My Agent&rdquo;).
        </p>
        {!clientId ? (
          <form onSubmit={handleRegister}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                required
                placeholder="Client name"
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
              />
              <button className="primary" type="submit" disabled={loading}>
                {loading ? "Registering\u2026" : "Register"}
              </button>
            </div>
            {error && <p style={{ color: "#d00", marginTop: 8 }}>{error}</p>}
          </form>
        ) : (
          <p style={{ color: "#1a7340" }}>
            ✓ Client registered. Your client ID: <code>{clientId}</code>
          </p>
        )}
      </section>

      <section style={{ marginBottom: 32 }}>
        <h3 style={{ marginBottom: 12 }}>Step 2 — Add Hive to Claude Code</h3>
        <p style={{ marginBottom: 8, color: "#555" }}>
          Add the following to your <code>~/.claude/settings.json</code>:
        </p>
        <pre
          style={{
            background: "#f5f5f5",
            border: "1px solid #e0e0e0",
            borderRadius: 6,
            padding: "12px 16px",
            fontSize: 13,
            overflowX: "auto",
          }}
        >
          {configSnippet}
        </pre>
        <button className="secondary" onClick={handleCopy} style={{ marginTop: 8 }}>
          {copied ? "Copied!" : "Copy"}
        </button>
      </section>

      <section>
        <h3 style={{ marginBottom: 12 }}>Step 3 — Connect</h3>
        <p style={{ color: "#555" }}>
          Open Claude Code. The next time you use a Hive memory tool, it will prompt you to
          authorise access via your browser. Complete the flow and you&apos;re done.
        </p>
      </section>
    </div>
  );
}
