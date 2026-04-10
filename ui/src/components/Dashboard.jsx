// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Area,
  AreaChart,
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
import { BarChart2, TrendingUp } from "lucide-react";
import { api } from "../api.js";

// Brand-aligned tool colors: navy/orange palette + complementary tones
const TOOL_COLORS = {
  remember:          "#e8a020", // brand orange
  recall:            "#1a73e8", // blue
  forget:            "#d93025", // red
  list_memories:     "#00897b", // teal
  summarize_context: "#9334e8", // purple
  search_memories:   "#34a853", // green
};

const SERVICE_COLORS = [
  "#1a1a2e", "#e8a020", "#1a73e8", "#d93025",
  "#9334e8", "#00897b", "#e65100", "#0277bd",
];

const PERIOD_OPTIONS = ["1h", "24h", "7d", "30d"];

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function buildInvocationSeries(metrics, tools) {
  const byTs = {};
  for (const tool of tools) {
    const safe = tool.replace(/_/g, "");
    const series = metrics[`inv_${safe}`] ?? { timestamps: [], values: [] };
    series.timestamps.forEach((ts, i) => {
      const label = ts.slice(0, 16).replace("T", " ");
      if (!byTs[label]) byTs[label] = { ts: label };
      byTs[label][tool] = (byTs[label][tool] ?? 0) + (series.values[i] ?? 0);
    });
  }
  return Object.values(byTs).sort((a, b) => a.ts.localeCompare(b.ts));
}

function buildLatencySeries(metrics, tools) {
  const byTs = {};
  for (const tool of tools) {
    const safe = tool.replace(/_/g, "");
    const series = metrics[`p99_${safe}`] ?? { timestamps: [], values: [] };
    series.timestamps.forEach((ts, i) => {
      const label = ts.slice(0, 16).replace("T", " ");
      if (!byTs[label]) byTs[label] = { ts: label };
      byTs[label][tool] = Math.round(series.values[i] ?? 0);
    });
  }
  return Object.values(byTs).sort((a, b) => a.ts.localeCompare(b.ts));
}

function buildCostSeries(monthly) {
  return monthly.map((m) => ({ month: m.period.slice(0, 7), ...m.by_service }));
}

function buildDailyCostSeries(daily) {
  return (daily ?? []).map((d) => ({ date: d.date, total: d.total }));
}

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

// ------------------------------------------------------------------
// Custom Tooltips
// ------------------------------------------------------------------

export function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "10px 14px",
        fontSize: 12,
        color: "var(--text)",
        boxShadow: "0 4px 12px rgba(0,0,0,.1)",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6, color: "var(--text-muted)" }}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 2 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: p.color, flexShrink: 0 }} />
          <span style={{ color: "var(--text-muted)" }}>{p.dataKey}:</span>
          <span style={{ fontWeight: 600 }}>{p.value}</span>
        </div>
      ))}
    </div>
  );
}

export function CustomCostTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "10px 14px",
        fontSize: 12,
        color: "var(--text)",
        boxShadow: "0 4px 12px rgba(0,0,0,.1)",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6, color: "var(--text-muted)" }}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 2 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: p.color, flexShrink: 0 }} />
          <span style={{ color: "var(--text-muted)" }}>{p.dataKey}:</span>
          <span style={{ fontWeight: 600 }}>{formatCostTooltip(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------
// Sub-components
// ------------------------------------------------------------------

function StatCard({ label, value }) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        padding: "18px 24px",
        flex: 1,
        minWidth: 120,
        boxShadow: "0 1px 4px rgba(0,0,0,.04)",
      }}
    >
      <div style={{ fontSize: 28, fontWeight: 700, color: "var(--text)" }}>{value ?? "—"}</div>
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4 }}>{label}</div>
    </div>
  );
}

function SectionHeader({ title }) {
  return (
    <h3
      style={{
        fontSize: 15,
        fontWeight: 700,
        color: "var(--text)",
        margin: "32px 0 16px",
        borderBottom: "1px solid var(--border)",
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
        background: "var(--surface)",
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

function SkeletonBlock({ width = "100%", height = 20, style = {} }) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius: 6,
        background: "var(--border)",
        opacity: 0.5,
        animation: "pulse 1.5s ease-in-out infinite",
        ...style,
      }}
    />
  );
}

function EmptyState({ icon: Icon, message }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
        padding: "32px 0",
        color: "var(--text-muted)",
      }}
    >
      <Icon size={28} strokeWidth={1.5} />
      <span style={{ fontSize: 13 }}>{message}</span>
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
  const [lastRefreshed, setLastRefreshed] = useState(null);
  const intervalRef = useRef(null);

  const TOOLS = ["remember", "recall", "forget", "list_memories", "summarize_context", "search_memories"];

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

    setLastRefreshed(new Date());
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
  const dailyCostData = costs ? buildDailyCostSeries(costs.daily ?? []) : [];
  const services = costs ? collectServices(costs.monthly ?? []) : [];

  const mtdCost = costs?.monthly?.length
    ? costs.monthly[costs.monthly.length - 1].total
    : null;

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

  const xAxisProps = {
    dataKey: "ts",
    tick: { fontSize: 11, fill: "var(--text-muted)" },
    interval: "preserveStartEnd",
    angle: -25,
    textAnchor: "end",
    height: 40,
  };

  return (
    <div>
      <style>{`@keyframes pulse { 0%,100%{opacity:.5} 50%{opacity:.25} }`}</style>

      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
        <h2 style={{ fontSize: 18, margin: 0, color: "var(--text)" }}>Dashboard</h2>
        <div style={{ display: "flex", gap: 4 }}>
          {PERIOD_OPTIONS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{
                background: period === p ? "#e8a020" : "var(--surface)",
                color: period === p ? "#1a1a2e" : "var(--text)",
                border: period === p ? "1px solid #e8a020" : "1px solid var(--border)",
                borderRadius: 6,
                padding: "4px 12px",
                fontSize: 13,
                fontWeight: period === p ? 700 : 400,
                cursor: "pointer",
              }}
            >
              {p}
            </button>
          ))}
        </div>
        {loading && <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Loading…</span>}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          {lastRefreshed && !loading && (
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Checked at {lastRefreshed.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={loadAll}
            style={{
              background: "transparent",
              border: "1px solid var(--border)",
              borderRadius: 6,
              padding: "4px 12px",
              fontSize: 13,
              cursor: "pointer",
              color: "var(--text)",
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Summary stats */}
      {loading && !stats ? (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} style={{ flex: 1, minWidth: 120, padding: "18px 24px", border: "1px solid var(--border)", borderRadius: 10 }}>
              <SkeletonBlock height={32} style={{ marginBottom: 8 }} />
              <SkeletonBlock height={14} width="60%" />
            </div>
          ))}
        </div>
      ) : stats && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <StatCard label="Total Memories" value={stats.total_memories} />
          <StatCard label="Total Clients" value={stats.total_clients} />
          <StatCard label="Total Users" value={stats.total_users} />
          <StatCard label="Events Today" value={stats.events_today} />
          <StatCard label="Events (7d)" value={stats.events_last_7_days} />
          {mtdCost !== null && (
            <StatCard label="AWS Cost (MTD)" value={`$${mtdCost.toFixed(2)}`} />
          )}
        </div>
      )}

      {/* Tool Invocations */}
      <SectionHeader title="Tool Invocations" />
      <ErrorBanner msg={metricsError} />
      {loading && !metrics ? (
        <SkeletonBlock height={260} />
      ) : invData.length > 0 ? (
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={invData} margin={{ bottom: 10 }}>
            <defs>
              {TOOLS.map((t) => (
                <linearGradient key={t} id={`inv_grad_${t}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={TOOL_COLORS[t]} stopOpacity={0.4} />
                  <stop offset="95%" stopColor={TOOL_COLORS[t]} stopOpacity={0.04} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="" vertical={false} stroke="var(--border)" />
            <XAxis {...xAxisProps} />
            <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 12, color: "var(--text-muted)" }} />
            {TOOLS.map((t) => (
              <Area
                key={t}
                type="monotone"
                dataKey={t}
                stroke={TOOL_COLORS[t]}
                fill={`url(#inv_grad_${t})`}
                strokeWidth={2}
                dot={false}
                animationDuration={400}
                activeDot={{ r: 5, strokeWidth: 2 }}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      ) : !metricsError && (
        <EmptyState icon={TrendingUp} message="No invocation data for this period." />
      )}

      {/* Tool Latency p99 */}
      <SectionHeader title="Tool Latency p99 (ms)" />
      {loading && !metrics ? (
        <SkeletonBlock height={220} />
      ) : latData.length > 0 ? (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={latData} margin={{ bottom: 10 }}>
            <defs>
              {TOOLS.map((t) => (
                <linearGradient key={t} id={`lat_grad_${t}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={TOOL_COLORS[t]} stopOpacity={0.4} />
                  <stop offset="95%" stopColor={TOOL_COLORS[t]} stopOpacity={0.04} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="" vertical={false} stroke="var(--border)" />
            <XAxis {...xAxisProps} />
            <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 12, color: "var(--text-muted)" }} />
            {TOOLS.map((t) => (
              <Area
                key={t}
                type="monotone"
                dataKey={t}
                stroke={TOOL_COLORS[t]}
                fill={`url(#lat_grad_${t})`}
                strokeWidth={2}
                dot={false}
                animationDuration={400}
                activeDot={{ r: 5, strokeWidth: 2 }}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      ) : !metricsError && (
        <EmptyState icon={TrendingUp} message="No latency data for this period." />
      )}

      {/* Auth Events */}
      <SectionHeader title="Auth Events" />
      {authData.length > 0 && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          {authData.map((d) => (
            <StatCard key={d.name} label={d.name} value={d.value} />
          ))}
        </div>
      )}

      {/* Daily AWS Spend */}
      <SectionHeader title="Daily AWS Spend (Last 30 Days)" />
      <ErrorBanner msg={costsError} />
      {loading && !costs ? (
        <SkeletonBlock height={200} />
      ) : dailyCostData.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={dailyCostData} margin={{ bottom: 10 }}>
            <defs>
              <linearGradient id="daily_cost_grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#e8a020" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#e8a020" stopOpacity={0.04} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="" vertical={false} stroke="var(--border)" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: "var(--text-muted)" }}
              interval="preserveStartEnd"
              angle={-25}
              textAnchor="end"
              height={40}
            />
            <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={formatCostTick} />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                return (
                  <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 14px", fontSize: 12, color: "var(--text)" }}>
                    <div style={{ fontWeight: 600, marginBottom: 4, color: "var(--text-muted)" }}>{label}</div>
                    <div style={{ fontWeight: 600 }}>{formatCostTooltip(payload[0].value)}</div>
                  </div>
                );
              }}
            />
            <Area
              type="monotone"
              dataKey="total"
              stroke="#e8a020"
              fill="url(#daily_cost_grad)"
              strokeWidth={2}
              dot={false}
              animationDuration={400}
            />
          </AreaChart>
        </ResponsiveContainer>
      ) : !costsError && (
        <EmptyState icon={BarChart2} message="No daily cost data available yet." />
      )}

      {/* Monthly AWS Spend */}
      <SectionHeader title="Monthly AWS Spend" />
      {costs && (
        <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "0 0 12px" }}>
          {costs.note}
        </p>
      )}
      {loading && !costs ? (
        <SkeletonBlock height={260} />
      ) : costData.length > 0 ? (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={costData} margin={{ bottom: 10 }}>
            <CartesianGrid strokeDasharray="" vertical={false} stroke="var(--border)" />
            <XAxis dataKey="month" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
            <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={formatCostTick} />
            <Tooltip content={<CustomCostTooltip />} />
            <Legend wrapperStyle={{ fontSize: 12, color: "var(--text-muted)" }} />
            {services.map((svc, i) => (
              <Bar
                key={svc}
                dataKey={svc}
                stackId="cost"
                fill={SERVICE_COLORS[i % SERVICE_COLORS.length]}
                radius={i === services.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                animationDuration={400}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      ) : !costsError && (
        <EmptyState icon={BarChart2} message="No cost data available yet." />
      )}
    </div>
  );
}
