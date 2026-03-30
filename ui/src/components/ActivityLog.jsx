import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState(null);
  const [days, setDays] = useState(7);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [evts, s] = await Promise.all([api.getActivity(days), api.getStats()]);
      setEvents(evts);
      setStats(s);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

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
              <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {error && <p style={{ color: "red", marginBottom: 12 }}>{error}</p>}

      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
        <label style={{ marginBottom: 0 }}>Show last</label>
        <select style={{ width: 80 }} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[1, 7, 14, 30, 90].map((d) => (
            <option key={d} value={d}>{d} days</option>
          ))}
        </select>
        <span style={{ color: "#888", fontSize: 13 }}>{events.length} events</span>
        <button className="secondary" onClick={load} style={{ marginLeft: "auto" }}>Refresh</button>
      </div>

      {loading && <p style={{ color: "#888" }}>Loading…</p>}

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
                <td colSpan={4} style={{ textAlign: "center", color: "#888", padding: 30 }}>
                  No activity in this period.
                </td>
              </tr>
            )}
            {events.map((e) => (
              <tr key={e.event_id}>
                <td style={{ whiteSpace: "nowrap", color: "#666", fontSize: 12 }}>
                  {new Date(e.timestamp).toLocaleString()}
                </td>
                <td>
                  <span
                    className="badge"
                    style={{
                      background: `${EVENT_COLORS[e.event_type] ?? "#888"}20`,
                      color: EVENT_COLORS[e.event_type] ?? "#888",
                    }}
                  >
                    {e.event_type}
                  </span>
                </td>
                <td>
                  <code style={{ fontSize: 11 }}>{e.client_id.slice(0, 8)}…</code>
                </td>
                <td style={{ fontSize: 12, color: "#555" }}>
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
