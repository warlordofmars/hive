// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api.js";

const TOOL_COLORS = {
  remember: "#1a73e8",
  recall: "#34a853",
  forget: "#d93025",
  list_memories: "#fbbc04",
  summarize_context: "#9334e8",
};

const PERIOD_OPTIONS = ["1h", "24h", "7d"];

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

/** Merge per-tool CloudWatch time-series into [{timestamp, tool, value}] rows. */
function buildInvocationSeries(metrics, tools) {
  const byTs = {};
  for (const tool of tools) {
    const safe = tool.replace("_", "");
    const series = metrics[`inv_${safe}`] ?? { timestamps: [], values: [] };
    series.timestamps.forEach((ts, i) => {
      const label = ts.slice(0, 16).replace("T", " ");
      if (!byTs[label]) byTs[label] = { ts: label };
      byTs[label][tool] = (byTs[label][tool] ?? 0) + (series.values[i] ?? 0);
    });
  }
  return Object.values(byTs).sort((a, b) => a.ts.localeCompare(b.ts));
}

/** Build [{ts, p99_remember, p99_recall, ...}] for latency chart. */
function buildLatencySeries(metrics, tools) {
  const byTs = {};
  for (const tool of tools) {
    const safe = tool.replace("_", "");
    const series = metrics[`p99_${safe}`] ?? { timestamps: [], values: [] };
    series.timestamps.forEach((ts, i) => {
      const label = ts.slice(0, 16).replace("T", " ");
      if (!byTs[label]) byTs[label] = { ts: label };
      byTs[label][tool] = Math.round(series.values[i] ?? 0);
    });
  }
  return Object.values(byTs).sort((a, b) => a.ts.localeCompare(b.ts));
}

/** Build [{month, ...services}] for cost bar chart. */
function buildCostSeries(monthly) {
  return monthly.map((m) => ({ month: m.period.slice(0, 7), ...m.by_service }));
}

/** Collect all unique AWS service names across months. */
function collectServices(monthly) {
  const set = new Set();
  for (const m of monthly) Object.keys(m.by_service).forEach((s) => set.add(s));
  return [...set];
}

export function formatCostTick(v) {
  return `$${v.toFixed(2)}`;
}

export function formatCostTooltip(v) {
  return `$${Number(v).toFixed(4)}`;
}

const SERVICE_COLORS = [
  "#1a73e8", "#34a853", "#fbbc04", "#d93025",
  "#9334e8", "#00897b", "#e65100", "#0277bd",
];

// ------------------------------------------------------------------
// Sub-components
// ------------------------------------------------------------------

function StatCard({ label, value }) {
  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid #e8e8e8",
        borderRadius: 10,
        padding: "18px 24px",
        flex: 1,
        minWidth: 120,
        boxShadow: "0 1px 4px rgba(0,0,0,.04)",
      }}
    >
      <div style={{ fontSize: 28, fontWeight: 700, color: "#1a1a2e" }}>{value ?? "—"}</div>
      <div style={{ fontSize: 13, color: "#666", marginTop: 4 }}>{label}</div>
    </div>
  );
}

function SectionHeader({ title }) {
  return (
    <h3
      style={{
        fontSize: 15,
        fontWeight: 700,
        color: "#1a1a2e",
        margin: "32px 0 16px",
        borderBottom: "1px solid #eee",
        paddingBottom: 8,
      }}
    >
      {title}
    </h3>
  );
}

function ErrorBanner({ msg }) {
  if (!msg) return null;
  return (
    <div
      style={{
        background: "#fff3f3",
        border: "1px solid #fcc",
        borderRadius: 6,
        padding: "8px 14px",
        color: "#c00",
        fontSize: 13,
        marginBottom: 12,
      }}
    >
      {msg}
    </div>
  );
}

// ------------------------------------------------------------------
// Main component
// ------------------------------------------------------------------

export default function Dashboard() {
  const [period, setPeriod] = useState("24h");
  const [stats, setStats] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [costs, setCosts] = useState(null);
  const [metricsError, setMetricsError] = useState("");
  const [costsError, setCostsError] = useState("");
  const [loading, setLoading] = useState(false);
  const intervalRef = useRef(null);

  const TOOLS = ["remember", "recall", "forget", "list_memories", "summarize_context"];

  const loadAll = useCallback(async () => {
    setLoading(true);
    setMetricsError("");
    setCostsError("");

    const [statsRes, metricsRes, costsRes] = await Promise.allSettled([
      api.getStats(),
      api.getMetrics(period),
      api.getCosts(),
    ]);

    if (statsRes.status === "fulfilled") setStats(statsRes.value);
    if (metricsRes.status === "fulfilled") setMetrics(metricsRes.value);
    else setMetricsError(metricsRes.reason?.message ?? "Failed to load metrics");
    if (costsRes.status === "fulfilled") setCosts(costsRes.value);
    else setCostsError(costsRes.reason?.message ?? "Failed to load costs");

    setLoading(false);
  }, [period]);

  useEffect(() => {
    loadAll();
    intervalRef.current = setInterval(loadAll, 60_000);
    return () => clearInterval(intervalRef.current);
  }, [loadAll]);

  const invData = metrics ? buildInvocationSeries(metrics.metrics ?? {}, TOOLS) : [];
  const latData = metrics ? buildLatencySeries(metrics.metrics ?? {}, TOOLS) : [];
  const costData = costs ? buildCostSeries(costs.monthly ?? []) : [];
  const services = costs ? collectServices(costs.monthly ?? []) : [];

  const authData = metrics
    ? [
        {
          name: "Tokens Issued",
          value: (metrics.metrics?.tokens_issued?.values ?? []).reduce((s, v) => s + v, 0),
        },
        {
          name: "Validation Failures",
          value: (metrics.metrics?.token_failures?.values ?? []).reduce((s, v) => s + v, 0),
        },
      ]
    : [];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
        <h2 style={{ fontSize: 18, margin: 0 }}>Dashboard</h2>
        <div style={{ display: "flex", gap: 4 }}>
          {PERIOD_OPTIONS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{
                background: period === p ? "#1a1a2e" : "#f0f0f0",
                color: period === p ? "#fff" : "#333",
                border: "none",
                borderRadius: 6,
                padding: "4px 12px",
                fontSize: 13,
                cursor: "pointer",
              }}
            >
              {p}
            </button>
          ))}
        </div>
        {loading && (
          <span style={{ fontSize: 12, color: "#999" }}>Loading…</span>
        )}
        <button
          onClick={loadAll}
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "1px solid #ddd",
            borderRadius: 6,
            padding: "4px 12px",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          Refresh
        </button>
      </div>

      {/* Summary stats */}
      {stats && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <StatCard label="Total Memories" value={stats.total_memories} />
          <StatCard label="Total Clients" value={stats.total_clients} />
          <StatCard label="Events Today" value={stats.events_today} />
          <StatCard label="Events (7d)" value={stats.events_last_7_days} />
        </div>
      )}

      {/* CloudWatch metrics */}
      <SectionHeader title="Tool Invocations" />
      <ErrorBanner msg={metricsError} />
      {invData.length > 0 && (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={invData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="ts" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend />
            {TOOLS.map((t) => (
              <Line
                key={t}
                type="monotone"
                dataKey={t}
                stroke={TOOL_COLORS[t]}
                dot={false}
                strokeWidth={2}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
      {invData.length === 0 && !metricsError && !loading && (
        <div style={{ color: "#999", fontSize: 13 }}>No invocation data for this period.</div>
      )}

      <SectionHeader title="Storage Latency p99 (ms)" />
      {latData.length > 0 && (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={latData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="ts" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend />
            {TOOLS.map((t) => (
              <Line
                key={t}
                type="monotone"
                dataKey={t}
                stroke={TOOL_COLORS[t]}
                dot={false}
                strokeWidth={2}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
      {latData.length === 0 && !metricsError && !loading && (
        <div style={{ color: "#999", fontSize: 13 }}>No latency data for this period.</div>
      )}

      <SectionHeader title="Auth Events" />
      {authData.length > 0 && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          {authData.map((d) => (
            <StatCard key={d.name} label={d.name} value={d.value} />
          ))}
        </div>
      )}

      {/* Cost data */}
      <SectionHeader title="Monthly AWS Spend" />
      <ErrorBanner msg={costsError} />
      {costs && (
        <p style={{ fontSize: 12, color: "#999", margin: "0 0 12px" }}>
          {costs.note}
        </p>
      )}
      {costData.length > 0 && (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={costData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={formatCostTick} />
            <Tooltip formatter={formatCostTooltip} />
            <Legend />
            {services.map((svc, i) => (
              <Bar
                key={svc}
                dataKey={svc}
                stackId="cost"
                fill={SERVICE_COLORS[i % SERVICE_COLORS.length]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
      {costData.length === 0 && !costsError && !loading && (
        <div style={{ color: "#999", fontSize: 13 }}>No cost data available yet.</div>
      )}
    </div>
  );
}
