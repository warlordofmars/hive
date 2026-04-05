// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api.js";
import ActivityLog from "./components/ActivityLog.jsx";
import AuthCallback from "./components/AuthCallback.jsx";
import ClientManager from "./components/ClientManager.jsx";
import Dashboard from "./components/Dashboard.jsx";
import HomePage from "./components/HomePage.jsx";
import LoginPage from "./components/LoginPage.jsx";
import MemoryBrowser from "./components/MemoryBrowser.jsx";
import SetupPanel from "./components/SetupPanel.jsx";
import UsersPanel from "./components/UsersPanel.jsx";

const BASE_TABS = [
  { id: "memories", label: "Memories" },
  { id: "clients", label: "OAuth Clients" },
  { id: "activity", label: "Activity Log" },
  { id: "setup", label: "Setup" },
];
const ADMIN_TABS = [
  ...BASE_TABS,
  { id: "users", label: "Users" },
  { id: "dashboard", label: "Dashboard" },
];

function parseToken(token) {
  if (!token) return null;
  try {
    return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

function isTokenValid(token) {
  const payload = parseToken(token);
  return payload ? payload.exp * 1000 > Date.now() : false;
}

function signOut() {
  localStorage.removeItem("hive_mgmt_token");
  window.location.replace("/");
}

function AppShell() {
  const [tab, setTab] = useState("memories");
  const [version, setVersion] = useState(null);
  const navigate = useNavigate();

  const token = localStorage.getItem("hive_mgmt_token") ?? "";

  if (!isTokenValid(token)) {
    return <LoginPage />;
  }

  const claims = parseToken(token);
  const isAdmin = claims.role === "admin";
  const userEmail = claims.email ?? "";
  const tabs = isAdmin ? ADMIN_TABS : BASE_TABS;

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((data) => setVersion(data.version ?? null))
      .catch(() => {});
  }, []);

  useEffect(() => {
    api.listClients()
      .then((data) => {
        if (data && data.items.length === 0) setTab("setup");
      })
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
        <span
          onClick={() => navigate("/")}
          style={{ fontWeight: 700, fontSize: 20, letterSpacing: 1, cursor: "pointer" }}
        >
          Hive
        </span>

        <nav style={{ display: "flex", gap: 4, flex: 1 }}>
          {tabs.map((t) => (
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

        {userEmail && (
          <span style={{ fontSize: 13, color: "rgba(255,255,255,.7)" }}>{userEmail}</span>
        )}

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
        {tab === "users" && isAdmin && <UsersPanel />}
        {tab === "setup" && <SetupPanel />}
        {tab === "dashboard" && isAdmin && <Dashboard />}
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

function HomeRoute() {
  const token = localStorage.getItem("hive_mgmt_token") ?? "";
  if (isTokenValid(token)) {
    return <Navigate to="/app" replace />;
  }
  return <HomePage />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomeRoute />} />
        <Route path="/app" element={<AppShell />} />
        <Route path="/oauth/callback" element={<AuthCallback />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
