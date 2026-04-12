// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useEffect, useState } from "react";
import { AlertTriangle, Check } from "lucide-react";
import { api } from "../api.js";
import { Button } from "./ui/button.jsx";
import { Card } from "./ui/card.jsx";

const STEP1_KEY = "hive_setup_step1_done";

export default function SetupPanel() {
  const mcpUrl = import.meta.env.VITE_MCP_BASE ?? `${globalThis.location.origin}/mcp`;
  const [activeTab, setActiveTab] = useState("code");
  const [copied, setCopied] = useState(false);
  const [step1Done, setStep1Done] = useState(() => !!localStorage.getItem(STEP1_KEY));
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // "ok" | "error"
  const [testError, setTestError] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [quota, setQuota] = useState(null);

  useEffect(function loadQuota() {
    api.getStats().then(function handleStats(s) {
      if (s && s.memory_limit != null) setQuota(s);
    }).catch(function handleError() {});
  }, []);

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

  async function handleDeleteAccount() {
    setDeleting(true);
    setDeleteError("");
    try {
      await api.deleteAccount();
      localStorage.removeItem("hive_mgmt_token");
      globalThis.location.replace("/");
    } catch (e) {
      setDeleteError(e.message ?? "Deletion failed");
      setDeleting(false);
    }
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

  function tabClassName(tab) {
    const isActive = activeTab === tab;
    return [
      "px-4 py-1.5 border border-[var(--border)] rounded-t cursor-pointer font-[inherit] text-[var(--text)]",
      "-mb-px",
      isActive
        ? "bg-[var(--bg)] border-b-[var(--bg)] font-semibold"
        : "bg-[var(--surface)]",
    ].join(" ");
  }

  return (
    <div className="max-w-[640px]">
      <h2 className="mb-6">Set up Hive</h2>

      {step1Done && step2Done && (
        <Card className="mb-6 border-l-4 border-l-[var(--success)] flex items-center gap-2.5">
          <Check size={18} className="text-[var(--success)] shrink-0" />
          <div>
            <strong>You're all set!</strong>
            <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
              Hive is connected and working. Head to the{" "}
              <button
                type="button"
                onClick={() => globalThis.dispatchEvent(new CustomEvent("hive:switch-tab", { detail: "memories" }))}
                className="bg-transparent border-none p-0 text-[var(--accent)] cursor-pointer font-inherit underline"
              >
                Memories
              </button>{" "}
              tab to get started.
            </p>
          </div>
        </Card>
      )}

      <section className="mb-8">
        <h3 className="mb-3 flex items-center gap-2">
          Step 1 — Connect your MCP client
          {step1Done && <Check size={16} className="text-[var(--success)]" />}
        </h3>
        <p className="mb-3 text-[var(--text-muted)]">
          Add Hive to your client config. OAuth is handled automatically on first use — no token
          needed.
        </p>

        <div className="flex gap-1 mb-0">
          <button className={tabClassName("code")} onClick={() => setActiveTab("code")}>
            Claude Code
          </button>
          <button className={tabClassName("cursor")} onClick={() => setActiveTab("cursor")}>
            Cursor
          </button>
          <button className={tabClassName("desktop")} onClick={() => setActiveTab("desktop")}>
            Claude Desktop
          </button>
        </div>

        <div className="border border-[var(--border)] rounded-b rounded-tr p-3 bg-[var(--bg)]">
          {activeTab === "code" && (
            <p className="mb-2 text-[var(--text-muted)] text-[13px]">
              Add to <code>~/.claude/settings.json</code>:
            </p>
          )}
          {activeTab === "cursor" && (
            <p className="mb-2 text-[var(--text-muted)] text-[13px]">
              Add to <code>~/.cursor/mcp.json</code> (create it if it doesn't exist):
            </p>
          )}
          {activeTab === "desktop" && (
            <p className="mb-2 text-[var(--text-muted)] text-[13px]">
              Add to{" "}
              <code>~/Library/Application Support/Claude/claude_desktop_config.json</code>.
              Requires <a href="https://github.com/geelen/mcp-remote" target="_blank" rel="noreferrer">mcp-remote</a> (
              <code>npx</code> will install it automatically):
            </p>
          )}
          <pre className="bg-[var(--surface)] border border-[var(--border)] rounded p-3 text-[13px] overflow-x-auto text-[var(--text)]">
            {configs[activeTab]}
          </pre>
          <Button variant="secondary" className="mt-2" onClick={handleCopy}>
            {copied ? "Copied!" : "Copy"}
          </Button>
        </div>
      </section>

      <section>
        <h3 className="mb-3 flex items-center gap-2">
          Step 2 — Authorise
          {step2Done && <Check size={16} className="text-[var(--success)]" />}
        </h3>
        <p className="text-[var(--text-muted)] mb-3">
          {activeTab === "code" && "Open Claude Code. The next time you use a Hive memory tool, it will prompt you to authorise access via your browser. Complete the flow and you're done."}
          {activeTab === "cursor" && "Restart Cursor. On first use it will open a browser window to complete the OAuth flow. After authorising, the connection is maintained automatically."}
          {activeTab === "desktop" && "Restart Claude Desktop. On first use it will open a browser window to complete the OAuth flow. After authorising, the connection is maintained automatically."}
        </p>
        <div className="flex items-center gap-3">
          <Button variant="secondary" onClick={handleTest} disabled={testing}>
            {testing ? "Testing…" : "Test connection"}
          </Button>
          {testResult === "ok" && (
            <span className="text-[13px] text-[var(--success)] flex items-center gap-1">
              <Check size={14} /> Connected
            </span>
          )}
          {testResult === "error" && (
            <span className="text-[13px] text-[var(--danger)]">{testError}</span>
          )}
        </div>
      </section>

      {quota && (
        <section className="mt-12 border-t border-[var(--border)] pt-8">
          <h3 className="mb-4">Usage</h3>
          <div className="flex flex-col gap-3.5">
            <QuotaBar label="Memories" used={quota.total_memories} limit={quota.memory_limit} />
            <QuotaBar label="Clients" used={quota.total_clients} limit={quota.client_limit} />
          </div>
        </section>
      )}

      <section className="mt-12 border-t border-[var(--border)] pt-8">
        <h3 className="mb-2 flex items-center gap-2 text-[var(--danger)]">
          <AlertTriangle size={18} />
          Danger Zone
        </h3>
        <p className="text-[var(--text-muted)] mb-4 text-sm">
          Permanently delete your account and all associated data — memories, OAuth clients, and
          your user profile. This action cannot be undone.
        </p>

        {!showDeleteConfirm ? (
          <Button
            variant="secondary"
            className="border-[var(--danger)] text-[var(--danger)]"
            onClick={() => setShowDeleteConfirm(true)}
          >
            Delete my account
          </Button>
        ) : (
          <Card className="border-l-4 border-l-[var(--danger)] max-w-[480px]">
            <p className="mb-4 font-semibold">
              Are you sure? This will permanently erase all your data.
            </p>
            {deleteError && (
              <p className="text-[var(--danger)] text-[13px] mb-3">{deleteError}</p>
            )}
            <div className="flex gap-2">
              <Button
                variant="danger"
                onClick={handleDeleteAccount}
                disabled={deleting}
              >
                {deleting ? "Deleting…" : "Yes, delete everything"}
              </Button>
              <Button
                variant="secondary"
                onClick={() => { setShowDeleteConfirm(false); setDeleteError(""); }}
              >
                Cancel
              </Button>
            </div>
          </Card>
        )}
      </section>
    </div>
  );
}

function QuotaBar({ label, used, limit }) {
  const pct = Math.min((used / limit) * 100, 100);
  const nearLimit = pct >= 80;
  const atLimit = pct >= 100;
  const color = atLimit ? "var(--danger)" : nearLimit ? "var(--amber)" : "var(--success)";
  return (
    <div>
      <div className="flex justify-between text-[13px] mb-1">
        <span>{label}</span>
        <span className={atLimit ? "text-[var(--danger)]" : "text-[var(--text-muted)]"}>
          {used} / {limit}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--border)] overflow-hidden">
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
}
