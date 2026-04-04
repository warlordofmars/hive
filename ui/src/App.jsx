// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useEffect, useState } from "react";
import ActivityLog from "./components/ActivityLog.jsx";
import AuthCallback from "./components/AuthCallback.jsx";
import ClientManager from "./components/ClientManager.jsx";
import LoginPage from "./components/LoginPage.jsx";
import MemoryBrowser from "./components/MemoryBrowser.jsx";

const TABS = [
  { id: "memories", label: "Memories" },
  { id: "clients", label: "OAuth Clients" },
  { id: "activity", label: "Activity Log" },
];

function isTokenValid(token) {
  if (!token) return false;
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return payload.exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

function signOut() {
  localStorage.removeItem("hive_token");
  window.location.replace("/");
}

export default function App() {
  const [tab, setTab] = useState("memories");
  const [version, setVersion] = useState(null);

  // Handle OAuth callback route
  if (window.location.pathname === "/oauth/callback") {
    return <AuthCallback />;
  }

  const token = localStorage.getItem("hive_token") ?? "";

  // Show login if no valid token
  if (!isTokenValid(token)) {
    return <LoginPage />;
  }

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((data) => setVersion(data.version ?? null))
      .catch(() => {});
  }, []);

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

        <button
          onClick={signOut}
          style={{
            background: "transparent",
            color: "rgba(255,255,255,.7)",
            border: "1px solid rgba(255,255,255,.3)",
            borderRadius: 6,
            padding: "5px 12px",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          Sign out
        </button>
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
