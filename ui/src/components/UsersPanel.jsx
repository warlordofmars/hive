// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import EmptyState from "./EmptyState.jsx";

export default function UsersPanel() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listUsers();
      setUsers(data ? data.items : []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDelete(userId) {
    if (!globalThis.confirm("Delete this user?")) return;
    try {
      await api.deleteUser(userId);
      setUsers((prev) => prev.filter((u) => u.user_id !== userId));
    } catch (e) {
      setError(e.message);
    }
  }

  if (loading) return <p>Loading…</p>;
  if (error) return <p style={{ color: "var(--danger)" }}>{error}</p>;

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Users</h2>
      {users.length === 0 ? (
        <EmptyState
          variant="users"
          title="No users found"
          description="Users appear here after they sign in for the first time via Google OAuth."
        />
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid var(--border)", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }}>Email</th>
              <th style={{ padding: "8px 12px" }}>Role</th>
              <th style={{ padding: "8px 12px" }}>Last Login</th>
              <th style={{ padding: "8px 12px" }} />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.user_id} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "8px 12px" }}>{u.email}</td>
                <td style={{ padding: "8px 12px" }}>{u.role}</td>
                <td style={{ padding: "8px 12px" }}>
                  {new Date(u.last_login_at).toLocaleString()}
                </td>
                <td style={{ padding: "8px 12px" }}>
                  <button className="danger" onClick={() => handleDelete(u.user_id)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
