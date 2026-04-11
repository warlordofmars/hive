// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Moon, Sun } from "lucide-react";
import { trackEvent, trackPageView } from "./analytics.js";
import { api } from "./api.js";
import ActivityLog from "./components/ActivityLog.jsx";
import AuthCallback from "./components/AuthCallback.jsx";
import ClientManager from "./components/ClientManager.jsx";
import Dashboard from "./components/Dashboard.jsx";
import ChangelogPage from "./components/ChangelogPage.jsx";
import FaqPage from "./components/FaqPage.jsx";
import HomePage from "./components/HomePage.jsx";
import LoginPage from "./components/LoginPage.jsx";
import McpClientsPage from "./components/McpClientsPage.jsx";
import PricingPage from "./components/PricingPage.jsx";
import StatusPage from "./components/StatusPage.jsx";
import UseCasesPage from "./components/UseCasesPage.jsx";
import MemoryBrowser from "./components/MemoryBrowser.jsx";
import SetupPanel from "./components/SetupPanel.jsx";
import UsersPanel from "./components/UsersPanel.jsx";
import { useTheme } from "./hooks/useTheme.js";

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

  function switchTab(id) {
    setTab(id);
    trackEvent("tab_view", { tab_name: id });
  }
  const [version, setVersion] = useState(null);
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();

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

  useEffect(() => {
    function onSwitchTab(e) { switchTab(e.detail); }
    window.addEventListener("hive:switch-tab", onSwitchTab);
    return () => window.removeEventListener("hive:switch-tab", onSwitchTab);
  }, []);

  const token = localStorage.getItem("hive_mgmt_token") ?? "";

  if (!isTokenValid(token)) {
    return <LoginPage />;
  }

  const claims = parseToken(token);
  const isAdmin = claims.role === "admin";
  const userEmail = claims.email ?? "";
  const tabs = isAdmin ? ADMIN_TABS : BASE_TABS;

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
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}
        >
          <img src="/logo.svg" alt="Hive" style={{ width: 28, height: 28 }} />
          <span style={{ fontWeight: 700, fontSize: 20, letterSpacing: 1 }}>Hive</span>
        </span>

        <nav style={{ display: "flex", gap: 4, flex: 1 }}>
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => switchTab(t.id)}
              style={{
                background: "transparent",
                color: "#fff",
                borderRadius: 6,
                padding: "6px 14px",
                fontSize: 14,
                borderBottom: tab === t.id ? "2px solid #e8a020" : "2px solid transparent",
              }}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <a
          href="/docs/"
          style={{ fontSize: 13, color: "rgba(255,255,255,.6)", textDecoration: "none" }}
        >
          Docs
        </a>

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

        <button
          onClick={toggle}
          style={{
            background: "transparent",
            color: "rgba(255,255,255,.7)",
            border: "1px solid rgba(255,255,255,.3)",
            borderRadius: 6,
            padding: "5px 10px",
            fontSize: 16,
            cursor: "pointer",
          }}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
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
            color: "var(--text-muted)",
            borderTop: "1px solid var(--border)",
          }}
        >
          <a
            href="/changelog"
            style={{ color: "inherit", textDecoration: "none" }}
            onMouseOver={(e) => (e.target.style.textDecoration = "underline")}
            onMouseOut={(e) => (e.target.style.textDecoration = "none")}
          >
            Hive {version}
          </a>
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

function RouteTracker() {
  const location = useLocation();
  useEffect(() => {
    trackPageView(location.pathname);
  }, [location.pathname]);
  return null;
}

export default function App() {
  useTheme(); // apply data-theme to <html> for all routes
  return (
    <BrowserRouter>
      <RouteTracker />
      <Routes>
        <Route path="/" element={<HomeRoute />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route path="/faq" element={<FaqPage />} />
        <Route path="/use-cases" element={<UseCasesPage />} />
        <Route path="/clients" element={<McpClientsPage />} />
        <Route path="/changelog" element={<ChangelogPage />} />
        <Route path="/status" element={<StatusPage />} />
        <Route path="/app" element={<AppShell />} />
        <Route path="/oauth/callback" element={<AuthCallback />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
