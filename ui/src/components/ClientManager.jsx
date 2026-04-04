// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

export default function ClientManager() {
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    client_name: "",
    redirect_uris: "",
    scope: "memories:read memories:write",
    token_endpoint_auth_method: "none",
  });
  const [newClient, setNewClient] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.listClients();
      setClients(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleCreate(e) {
    e.preventDefault();
    try {
      const resp = await api.createClient({
        client_name: form.client_name,
        redirect_uris: form.redirect_uris.split(",").map((u) => u.trim()).filter(Boolean),
        scope: form.scope,
        token_endpoint_auth_method: form.token_endpoint_auth_method,
      });
      setNewClient(resp);
      setCreating(false);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDelete(id) {
    if (!confirm("Delete this OAuth client?")) return;
    try {
      await api.deleteClient(id);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 16, gap: 10 }}>
        <h2 style={{ flex: 1, fontSize: 18 }}>OAuth Clients</h2>
        <button className="primary" onClick={() => { setCreating(true); setNewClient(null); }}>
          + Register Client
        </button>
      </div>

      {error && <p style={{ color: "red", marginBottom: 12 }}>{error}</p>}

      {newClient && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid #34a853" }}>
          <strong>Client registered successfully.</strong>
          <p style={{ marginTop: 8, fontSize: 13 }}>
            <b>Client ID:</b> <code>{newClient.client_id}</code>
          </p>
          {newClient.client_secret && (
            <p style={{ marginTop: 4, fontSize: 13, color: "#d93025" }}>
              <b>Client Secret (save now, not shown again):</b>{" "}
              <code>{newClient.client_secret}</code>
            </p>
          )}
          <button className="secondary" style={{ marginTop: 12 }} onClick={() => setNewClient(null)}>
            Dismiss
          </button>
        </div>
      )}

      {creating && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 16, fontSize: 15 }}>Register New Client (RFC 7591)</h3>
          <form onSubmit={handleCreate}>
            <div style={{ marginBottom: 10 }}>
              <label>Client Name</label>
              <input
                required
                value={form.client_name}
                onChange={(e) => setForm({ ...form, client_name: e.target.value })}
                placeholder="My Agent"
              />
            </div>
            <div style={{ marginBottom: 10 }}>
              <label>Redirect URIs (comma-separated)</label>
              <input
                value={form.redirect_uris}
                onChange={(e) => setForm({ ...form, redirect_uris: e.target.value })}
                placeholder="http://localhost:3000/callback"
              />
            </div>
            <div style={{ marginBottom: 10 }}>
              <label>Scope</label>
              <input
                value={form.scope}
                onChange={(e) => setForm({ ...form, scope: e.target.value })}
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label>Auth Method</label>
              <select
                value={form.token_endpoint_auth_method}
                onChange={(e) => setForm({ ...form, token_endpoint_auth_method: e.target.value })}
              >
                <option value="none">none (public)</option>
                <option value="client_secret_post">client_secret_post</option>
                <option value="client_secret_basic">client_secret_basic</option>
              </select>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="primary" type="submit">Register</button>
              <button className="secondary" type="button" onClick={() => setCreating(false)}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      {loading && <p style={{ color: "#888" }}>Loading…</p>}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Client ID</th>
              <th>Type</th>
              <th>Scope</th>
              <th>Registered</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {clients.length === 0 && !loading && (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", color: "#888", padding: 30 }}>
                  No clients registered.
                </td>
              </tr>
            )}
            {clients.map((c) => (
              <tr key={c.client_id}>
                <td><strong>{c.client_name}</strong></td>
                <td><code style={{ fontSize: 12 }}>{c.client_id}</code></td>
                <td>{c.token_endpoint_auth_method === "none" ? "public" : "confidential"}</td>
                <td>{c.scope}</td>
                <td>{new Date(c.client_id_issued_at * 1000).toLocaleDateString()}</td>
                <td>
                  <button className="danger" onClick={() => handleDelete(c.client_id)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
