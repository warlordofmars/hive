// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import EmptyState from "./EmptyState.jsx";

const EVENT_COLORS = {
  memory_created: "#34a853",
  memory_updated: "#fbbc04",
  memory_deleted: "#d93025",
  memory_recalled: "#1a73e8",
  memory_listed: "#1a73e8",
  context_summarized: "#9334e8",
  token_issued: "#00897b",
  token_revoked: "#e65100",
  client_registered: "#0277bd",
  client_deleted: "#c62828",
};

export default function ActivityLog() {
  const [events, setEvents] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [limit, setLimit] = useState(100);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState(null);
  const [days, setDays] = useState(7);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [page, s] = await Promise.all([api.getActivity(days, { limit }), api.getStats()]);
      setEvents(page.items);
      setHasMore(page.has_more);
      setStats(s);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [days, limit]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h2 style={{ fontSize: 18, marginBottom: 16 }}>Activity Log</h2>

      {/* Stats bar */}
      {stats && (
        <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
          {[
            { label: "Total Memories", value: stats.total_memories },
            { label: "Total Clients", value: stats.total_clients },
            { label: "Events Today", value: stats.events_today },
            { label: "Events (7 days)", value: stats.events_last_7_days },
          ].map(({ label, value }) => (
            <div key={label} className="card" style={{ flex: 1, textAlign: "center" }}>
              <div style={{ fontSize: 28, fontWeight: 700 }}>{value}</div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {error && <p style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</p>}

      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
        <label style={{ marginBottom: 0 }}>Show last</label>
        <select style={{ width: 80 }} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[1, 7, 14, 30, 90].map((d) => (
            <option key={d} value={d}>{d} days</option>
          ))}
        </select>
        <label style={{ marginBottom: 0, marginLeft: 8 }}>Limit</label>
        <select style={{ width: 80 }} value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
          {[50, 100, 250, 500].map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <span style={{ color: "var(--text-muted)", fontSize: 13 }}>
          {events.length} events{hasMore ? " (more available)" : ""}
        </span>
        <button className="secondary" onClick={load} style={{ marginLeft: "auto" }}>Refresh</button>
      </div>

      {loading && <p style={{ color: "var(--text-muted)" }}>Loading…</p>}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Client</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 && !loading && (
              <tr>
                <td colSpan={4} style={{ padding: 0 }}>
                  <EmptyState
                    variant="activity"
                    title="No activity in this period"
                    description="Events will appear here as your MCP clients use Hive tools."
                  />
                </td>
              </tr>
            )}
            {events.map((e) => (
              <tr key={e.event_id}>
                <td style={{ whiteSpace: "nowrap", color: "var(--text-muted)", fontSize: 12 }}>
                  {new Date(e.timestamp).toLocaleString()}
                </td>
                <td>
                  <span
                    className="badge"
                    style={{
                      background: `${EVENT_COLORS[e.event_type] ?? "var(--text-muted)"}20`,
                      color: EVENT_COLORS[e.event_type] ?? "var(--text-muted)",
                      border: "none",
                    }}
                  >
                    {e.event_type}
                  </span>
                </td>
                <td>
                  <code style={{ fontSize: 11 }}>{e.client_id.slice(0, 8)}…</code>
                </td>
                <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  {Object.entries(e.metadata)
                    .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
                    .join(" · ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
