// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

export default function MemoryBrowser() {
  const [memories, setMemories] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [editing, setEditing] = useState(null); // memory object or null
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ key: "", value: "", tags: "" });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setNextCursor(null);
    try {
      const data = await api.listMemories(tagFilter || undefined);
      setMemories(data.items);
      setNextCursor(data.next_cursor ?? null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [tagFilter]);

  useEffect(() => {
    load();
  }, [load]);

  async function loadMore() {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const data = await api.listMemories(tagFilter || undefined, { cursor: nextCursor });
      setMemories((prev) => [...prev, ...data.items]);
      setNextCursor(data.next_cursor ?? null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleCreate(e) {
    e.preventDefault();
    try {
      await api.createMemory({
        key: form.key,
        value: form.value,
        tags: form.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
      setCreating(false);
      setForm({ key: "", value: "", tags: "" });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleUpdate(e) {
    e.preventDefault();
    try {
      await api.updateMemory(editing.memory_id, {
        value: form.value,
        tags: form.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
      setEditing(null);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDelete(id) {
    if (!confirm("Delete this memory?")) return;
    try {
      await api.deleteMemory(id);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  function openEdit(m) {
    setEditing(m);
    setForm({ key: m.key, value: m.value, tags: m.tags.join(", ") });
    setCreating(false);
  }

  function openCreate() {
    setCreating(true);
    setEditing(null);
    setForm({ key: "", value: "", tags: "" });
  }

  return (
    <div style={{ display: "flex", gap: 20 }}>
      {/* List */}
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "center" }}>
          <h2 style={{ flex: 1, fontSize: 18 }}>Memories</h2>
          <input
            style={{ width: 180 }}
            placeholder="Filter by tag"
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
          />
          <button className="primary" onClick={openCreate}>
            + New
          </button>
        </div>

        {error && <p style={{ color: "red", marginBottom: 12 }}>{error}</p>}
        {loading && <p style={{ color: "#888" }}>Loading…</p>}

        {!loading && memories.length === 0 && (
          <div className="card" style={{ textAlign: "center", color: "#888", padding: 40 }}>
            No memories found.
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {memories.map((m) => (
            <div
              key={m.memory_id}
              className="card"
              style={{ cursor: "pointer", borderLeft: "4px solid #1a73e8" }}
              onClick={() => openEdit(m)}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                }}
              >
                <div>
                  <strong>{m.key}</strong>
                  <p
                    style={{
                      marginTop: 4,
                      color: "#555",
                      fontSize: 13,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {m.value.length > 160 ? m.value.slice(0, 160) + "…" : m.value}
                  </p>
                  <div style={{ marginTop: 6 }}>
                    {m.tags.map((t) => (
                      <span key={t} className="badge">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
                <button
                  className="danger"
                  style={{ marginLeft: 12, flexShrink: 0 }}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(m.memory_id);
                  }}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>

        {nextCursor && (
          <div style={{ textAlign: "center", marginTop: 16 }}>
            <button className="secondary" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </div>

      {/* Side form */}
      {(creating || editing) && (
        <div style={{ width: 360 }}>
          <div className="card">
            <h3 style={{ marginBottom: 16, fontSize: 16 }}>
              {creating ? "New Memory" : `Edit: ${editing.key}`}
            </h3>
            <form onSubmit={creating ? handleCreate : handleUpdate}>
              {creating && (
                <div style={{ marginBottom: 12 }}>
                  <label>Key</label>
                  <input
                    required
                    value={form.key}
                    onChange={(e) => setForm({ ...form, key: e.target.value })}
                    placeholder="unique-key"
                  />
                </div>
              )}
              <div style={{ marginBottom: 12 }}>
                <label>Value</label>
                <textarea
                  required
                  rows={6}
                  value={form.value}
                  onChange={(e) => setForm({ ...form, value: e.target.value })}
                  placeholder="Memory content…"
                />
              </div>
              <div style={{ marginBottom: 16 }}>
                <label>Tags (comma-separated)</label>
                <input
                  value={form.tags}
                  onChange={(e) => setForm({ ...form, tags: e.target.value })}
                  placeholder="tag1, tag2"
                />
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="primary" type="submit">
                  Save
                </button>
                <button
                  className="secondary"
                  type="button"
                  onClick={() => {
                    setCreating(false);
                    setEditing(null);
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
