// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useEffect, useState } from "react";
import MemoryBrowser from "./components/MemoryBrowser.jsx";
import ClientManager from "./components/ClientManager.jsx";
import ActivityLog from "./components/ActivityLog.jsx";
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

const TABS = [
  { id: "memories", label: "Memories" },
  { id: "clients", label: "OAuth Clients" },
  { id: "activity", label: "Activity Log" },
];

export default function App() {
  const [tab, setTab] = useState("memories");
  const [token, setToken] = useState(localStorage.getItem("hive_token") ?? "");
  const [version, setVersion] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((data) => setVersion(data.version ?? null))
      .catch(() => {});
  }, []);

  function saveToken(t) {
    setToken(t);
    localStorage.setItem("hive_token", t);
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <header
        style={{
          background: "#1a1a2e",
          color: "#fff",
          padding: "0 24px",
          display: "flex",
          alignItems: "center",
          gap: 24,
          height: 56,
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 20, letterSpacing: 1 }}>Hive</span>

        <nav style={{ display: "flex", gap: 4, flex: 1 }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                background: tab === t.id ? "rgba(255,255,255,.15)" : "transparent",
                color: "#fff",
                borderRadius: 6,
                padding: "6px 14px",
                fontSize: 14,
              }}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            style={{ width: 260, background: "rgba(255,255,255,.1)", color: "#fff", border: "1px solid rgba(255,255,255,.3)" }}
            type="password"
            placeholder="Bearer token"
            value={token}
            onChange={(e) => saveToken(e.target.value)}
          />
        </div>
      </header>

      <main style={{ flex: 1, padding: 24, maxWidth: 1100, margin: "0 auto", width: "100%" }}>
        {tab === "memories" && <MemoryBrowser />}
        {tab === "clients" && <ClientManager />}
        {tab === "activity" && <ActivityLog />}
      </main>

      {version && (
        <footer
          style={{
            textAlign: "center",
            padding: "8px 0",
            fontSize: 12,
            color: "#888",
            borderTop: "1px solid #eee",
          }}
        >
          Hive {version}
        </footer>
      )}
    </div>
  );
}
