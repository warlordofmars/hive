// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { X } from "lucide-react";
import { api } from "../api.js";
import EmptyState from "./EmptyState.jsx";

// ------------------------------------------------------------------
// TagPicker — combobox that shows suggestions from known tags,
// renders the selected tag as a removable chip, and calls
// onSelect(tag | "") when the filter changes.
// ------------------------------------------------------------------

export function TagPicker({ knownTags, value, onSelect }) {
  const [inputValue, setInputValue] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const listRef = useRef(null);

  const suggestions = knownTags.filter(
    (t) => t.toLowerCase().includes(inputValue.toLowerCase()) && t !== value,
  );

  function selectTag(tag) {
    onSelect(tag);
    setInputValue("");
    setOpen(false);
    setActiveIndex(-1);
  }

  function clearTag() {
    onSelect("");
    setInputValue("");
    setOpen(false);
    setActiveIndex(-1);
  }

  function handleInputChange(e) {
    setInputValue(e.target.value);
    setOpen(true);
    setActiveIndex(-1);
  }

  function handleKeyDown(e) {
    if (!open || suggestions.length === 0) {
      if (e.key === "Escape") setOpen(false);
      else if (e.key === "Enter" && inputValue.trim()) {
        e.preventDefault();
        selectTag(inputValue.trim());
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      selectTag(suggestions[activeIndex]);
    } else if (e.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  // Scroll active item into view
  useEffect(() => {
    if (activeIndex >= 0 && listRef.current) {
      const item = listRef.current.children[activeIndex];
      item?.scrollIntoView?.({ block: "nearest" });
    }
  }, [activeIndex]);

  return (
    <div style={{ position: "relative", width: 160 }}>
      {value ? (
        // Selected chip
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 8px",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 999,
            fontSize: 12,
            fontWeight: 600,
            color: "var(--text)",
            width: "100%",
            boxSizing: "border-box",
          }}
        >
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {value}
          </span>
          <button
            type="button"
            aria-label="Clear tag filter"
            onClick={clearTag}
            style={{
              background: "transparent",
              border: "none",
              padding: 0,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              color: "var(--text-muted)",
              flexShrink: 0,
            }}
          >
            <X size={11} />
          </button>
        </div>
      ) : (
        // Input
        <input
          id="tag-filter-input"
          role="combobox"
          style={{ width: "100%" }}
          placeholder="Filter by tag"
          value={inputValue}
          autoComplete="off"
          onChange={handleInputChange}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={handleKeyDown}
          aria-autocomplete="list"
          aria-expanded={open && suggestions.length > 0}
          aria-controls="tag-suggestions"
          aria-activedescendant={activeIndex >= 0 ? `tag-opt-${activeIndex}` : undefined}
        />
      )}

      {open && suggestions.length > 0 && (
        <div
          id="tag-suggestions"
          ref={listRef}
          role="listbox" /* NOSONAR — ARIA combobox pattern; native <select> cannot serve as a positioned overlay */
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            boxShadow: "0 4px 12px rgba(0,0,0,.12)",
            maxHeight: 200,
            overflowY: "auto",
            zIndex: 100,
            margin: 0,
            padding: "4px 0",
          }}
        >
          {suggestions.map((t, i) => (
            <div
              key={t}
              id={`tag-opt-${i}`}
              role="option"
              tabIndex={-1}
              aria-selected={i === activeIndex}
              onMouseDown={() => selectTag(t)}
              style={{
                padding: "6px 12px",
                fontSize: 13,
                cursor: "pointer",
                background: i === activeIndex ? "var(--accent)" : "transparent",
                color: i === activeIndex ? "var(--accent-fg)" : "var(--text)",
              }}
            >
              {t}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

TagPicker.propTypes = {
  knownTags: PropTypes.arrayOf(PropTypes.string).isRequired,
  value: PropTypes.string.isRequired,
  onSelect: PropTypes.func.isRequired,
};

// ------------------------------------------------------------------
// MemoryBrowser
// ------------------------------------------------------------------

export default function MemoryBrowser() {
  const [memories, setMemories] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearchMode, setIsSearchMode] = useState(false);
  const [editing, setEditing] = useState(null); // memory object or null
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ key: "", value: "", tags: "" });
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const searchDebounceRef = useRef(null);
  const listRef = useRef(null);

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

  const runSearch = useCallback(async (query) => {
    setLoading(true);
    setError("");
    setNextCursor(null);
    try {
      const data = await api.searchMemories(query);
      setMemories(data.items);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // When tag filter changes, run list (not search)
  useEffect(() => {
    if (!isSearchMode) load();
  }, [load, isSearchMode]);

  // Debounce search input
  useEffect(() => {
    if (!searchQuery) return;
    clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      runSearch(searchQuery);
    }, 400);
    return () => clearTimeout(searchDebounceRef.current);
  }, [searchQuery, runSearch]);

  // Collect distinct tags from loaded memories for suggestions
  const knownTags = [...new Set(memories.flatMap((m) => m.tags))].sort((a, b) => a.localeCompare(b));

  function handleTagSelect(tag) {
    setTagFilter(tag);
    if (tag) {
      setSearchQuery("");
      setIsSearchMode(false);
    }
  }

  function handleSearchQueryChange(e) {
    const val = e.target.value;
    setSearchQuery(val);
    if (val) {
      setTagFilter("");
      setIsSearchMode(true);
    } else {
      setIsSearchMode(false);
    }
  }

  async function loadMore() {
    if (!nextCursor) return; /* c8 ignore next */
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

  function closePanel() {
    setEditing(null);
    setCreating(false);
  }

  // Programmatically focus the card at focusedIndex when it changes
  useEffect(() => {
    if (focusedIndex >= 0 && listRef.current) {
      const li = listRef.current.children[focusedIndex];
      li?.querySelector("button.card")?.focus();
    }
  }, [focusedIndex]);

  function handleCardKeyDown(e, m) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusedIndex((i) => Math.min(i + 1, memories.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openEdit(m);
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      handleDelete(m.memory_id);
    } else if (e.key === "Escape") {
      closePanel();
    }
  }

  return (
    <div style={{ display: "flex", gap: 20 }}>
      {/* List */}
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "center" }}>
          <h2 style={{ flex: 1, fontSize: 18 }}>Memories</h2>
          <input
            style={{ width: 180 }}
            placeholder="Search by meaning…"
            value={searchQuery}
            onChange={handleSearchQueryChange}
          />
          <TagPicker knownTags={knownTags} value={tagFilter} onSelect={handleTagSelect} />
          <button className="primary" onClick={openCreate}>
            + New
          </button>
        </div>

        {error && <p style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</p>}
        {loading && <p style={{ color: "var(--text-muted)" }}>Loading…</p>}

        {!loading && memories.length === 0 && (
          <div className="card" style={{ padding: 0 }}>
            <EmptyState
              variant="memories"
              title="No memories yet"
              description="Use the remember tool in your MCP client to store your first memory."
              action={<button className="primary" onClick={openCreate}>+ New Memory</button>}
            />
          </div>
        )}

        <ul
          ref={listRef}
          style={{ display: "flex", flexDirection: "column", gap: 10, listStyle: "none", margin: 0, padding: 0 }}
        >
          {memories.map((m, i) => (
            <li key={m.memory_id} style={{ display: "flex", alignItems: "flex-start", gap: 0 }}>
              <button
                type="button"
                className="card"
                style={{ cursor: "pointer", borderLeft: "4px solid var(--accent)", flex: 1, textAlign: "left", background: "var(--surface)" }}
                onClick={() => openEdit(m)}
                onFocus={() => setFocusedIndex(i)}
                onKeyDown={(e) => handleCardKeyDown(e, m)}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <strong>{m.key}</strong>
                    {m.score !== undefined && (
                      <span
                        className="badge"
                        style={{
                          background: "var(--surface)",
                          color: "var(--text)",
                          border: "1px solid var(--border)",
                        }}
                      >
                        {Math.round(m.score * 100)}% match
                      </span>
                    )}
                  </div>
                  <p
                    style={{
                      marginTop: 4,
                      color: "var(--text-muted)",
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
              </button>
              <button
                className="danger"
                style={{ marginLeft: 12, flexShrink: 0, alignSelf: "center" }}
                onClick={() => handleDelete(m.memory_id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>

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
                  <label htmlFor="memory-key">Key</label>
                  <input
                    id="memory-key"
                    required
                    value={form.key}
                    onChange={(e) => setForm({ ...form, key: e.target.value })}
                    placeholder="unique-key"
                  />
                </div>
              )}
              <div style={{ marginBottom: 12 }}>
                <label htmlFor="memory-value">Value</label>
                <textarea
                  id="memory-value"
                  required
                  rows={6}
                  value={form.value}
                  onChange={(e) => setForm({ ...form, value: e.target.value })}
                  placeholder="Memory content…"
                />
              </div>
              <div style={{ marginBottom: 16 }}>
                <label htmlFor="memory-tags">Tags (comma-separated)</label>
                <input
                  id="memory-tags"
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
                  onClick={closePanel}
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
