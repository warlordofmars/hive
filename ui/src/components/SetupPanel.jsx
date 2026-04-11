// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useState } from "react";
import { Check } from "lucide-react";
import { api } from "../api.js";

const STEP1_KEY = "hive_setup_step1_done";

export default function SetupPanel() {
  const mcpUrl = import.meta.env.VITE_MCP_BASE ?? `${globalThis.location.origin}/mcp`;
  const [activeTab, setActiveTab] = useState("code");
  const [copied, setCopied] = useState(false);
  const [step1Done, setStep1Done] = useState(() => !!localStorage.getItem(STEP1_KEY));
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // "ok" | "error"
  const [testError, setTestError] = useState("");

  const step2Done = testResult === "ok";

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
    localStorage.setItem(STEP1_KEY, "1");
    setStep1Done(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    setTestError("");
    try {
      await api.listMemories();
      setTestResult("ok");
    } catch (e) {
      setTestResult("error");
      setTestError(e.message ?? "Connection failed");
    } finally {
      setTesting(false);
    }
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

      {step1Done && step2Done && (
        <div
          className="card"
          style={{ marginBottom: 24, borderLeft: "4px solid var(--success)", display: "flex", alignItems: "center", gap: 10 }}
        >
          <Check size={18} style={{ color: "var(--success)", flexShrink: 0 }} />
          <div>
            <strong>You're all set!</strong>
            <p style={{ margin: "2px 0 0", fontSize: 13, color: "var(--text-muted)" }}>
              Hive is connected and working. Head to the{" "}
              <a href="#" onClick={(e) => { e.preventDefault(); globalThis.dispatchEvent(new CustomEvent("hive:switch-tab", { detail: "memories" })); }}>
                Memories
              </a>{" "}
              tab to get started.
            </p>
          </div>
        </div>
      )}

      <section style={{ marginBottom: 32 }}>
        <h3 style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
          Step 1 — Connect your MCP client
          {step1Done && <Check size={16} style={{ color: "var(--success)" }} />}
        </h3>
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
        <h3 style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
          Step 2 — Authorise
          {step2Done && <Check size={16} style={{ color: "var(--success)" }} />}
        </h3>
        <p style={{ color: "var(--text-muted)", marginBottom: 12 }}>
          {activeTab === "code" && "Open Claude Code. The next time you use a Hive memory tool, it will prompt you to authorise access via your browser. Complete the flow and you're done."}
          {activeTab === "cursor" && "Restart Cursor. On first use it will open a browser window to complete the OAuth flow. After authorising, the connection is maintained automatically."}
          {activeTab === "desktop" && "Restart Claude Desktop. On first use it will open a browser window to complete the OAuth flow. After authorising, the connection is maintained automatically."}
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button className="secondary" onClick={handleTest} disabled={testing}>
            {testing ? "Testing…" : "Test connection"}
          </button>
          {testResult === "ok" && (
            <span style={{ fontSize: 13, color: "var(--success)", display: "flex", alignItems: "center", gap: 4 }}>
              <Check size={14} /> Connected
            </span>
          )}
          {testResult === "error" && (
            <span style={{ fontSize: 13, color: "var(--danger)" }}>{testError}</span>
          )}
        </div>
      </section>
    </div>
  );
}
