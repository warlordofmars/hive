// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useRef, useState } from "react";
import PropTypes from "prop-types";
import { X } from "lucide-react";
import { api } from "../api.js";
import EmptyState from "./EmptyState.jsx";
import { AlertDialog } from "./ui/alert-dialog.jsx";
import { Badge } from "./ui/badge.jsx";
import { Button } from "./ui/button.jsx";
import { Card } from "./ui/card.jsx";
import { Input } from "./ui/input.jsx";
import { Label } from "./ui/label.jsx";
import { Textarea } from "./ui/textarea.jsx";

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
      else if (e.key === "Enter" && e.target.value.trim()) {
        e.preventDefault();
        selectTag(e.target.value.trim());
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIndex >= 0) {
        selectTag(suggestions[activeIndex]);
      } else if (e.target.value.trim()) {
        selectTag(e.target.value.trim());
      }
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
    <div className="relative w-40">
      {value ? (
        // Selected chip
        <div className="inline-flex items-center gap-1 px-2 py-1 bg-[var(--surface)] border border-[var(--border)] rounded-full text-xs font-semibold text-[var(--text)] w-full box-border">
          <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
            {value}
          </span>
          <button
            type="button"
            aria-label="Clear tag filter"
            onClick={clearTag}
            className="bg-transparent border-none p-0 cursor-pointer flex items-center text-[var(--text-muted)] shrink-0"
          >
            <X size={11} />
          </button>
        </div>
      ) : (
        // Input
        <Input
          id="tag-filter-input"
          role="combobox"
          className="w-full"
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
          className="absolute top-[calc(100%+4px)] left-0 right-0 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] shadow-lg max-h-48 overflow-y-auto z-[100] py-1"
        >
          {suggestions.map((t, i) => (
            <div
              key={t}
              id={`tag-opt-${i}`}
              role="option"
              tabIndex={-1}
              aria-selected={i === activeIndex}
              onMouseDown={() => selectTag(t)}
              className="px-3 py-1.5 text-[13px] cursor-pointer"
              style={{
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
  const [pendingDelete, setPendingDelete] = useState(null);
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
    try {
      await api.deleteMemory(id);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setPendingDelete(null);
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
      li?.querySelector("[data-testid='memory-card']")?.focus();
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
    <div className="flex gap-5">
      <AlertDialog
        open={pendingDelete !== null}
        title="Delete this memory?"
        description="This action cannot be undone."
        onConfirm={() => handleDelete(pendingDelete)}
        onCancel={() => setPendingDelete(null)}
      />

      {/* List */}
      <div className="flex-1">
        <div className="flex gap-2.5 mb-4 items-center">
          <h2 className="flex-1 text-lg font-semibold">Memories</h2>
          <Input
            className="w-44"
            placeholder="Search by meaning…"
            value={searchQuery}
            onChange={handleSearchQueryChange}
          />
          <TagPicker knownTags={knownTags} value={tagFilter} onSelect={handleTagSelect} />
          <Button onClick={openCreate}>+ New</Button>
        </div>

        {error && <p className="text-[var(--danger)] mb-3">{error}</p>}
        {loading && <p className="text-[var(--text-muted)]">Loading…</p>}

        {!loading && memories.length === 0 && (
          <Card className="p-0">
            <EmptyState
              variant="memories"
              title="No memories yet"
              description="Use the remember tool in your MCP client to store your first memory."
              action={<Button onClick={openCreate}>+ New Memory</Button>}
            />
          </Card>
        )}

        <ul ref={listRef} className="flex flex-col gap-2.5 list-none m-0 p-0">
          {memories.map((m, i) => (
            <li key={m.memory_id} className="flex items-start">
              <button
                type="button"
                data-testid="memory-card"
                className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] p-4 cursor-pointer border-l-4 border-l-[var(--accent)] flex-1 text-left"
                onClick={() => openEdit(m)}
                onFocus={() => setFocusedIndex(i)}
                onKeyDown={(e) => handleCardKeyDown(e, m)}
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <strong>{m.key}</strong>
                    {m.score !== undefined && (
                      <Badge>{Math.round(m.score * 100)}% match</Badge>
                    )}
                  </div>
                  <p className="mt-1 text-[var(--text-muted)] text-[13px] whitespace-pre-wrap">
                    {m.value.length > 160 ? m.value.slice(0, 160) + "…" : m.value}
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {m.tags.map((t) => (
                      <Badge key={t}>{t}</Badge>
                    ))}
                  </div>
                </div>
              </button>
              <Button
                variant="danger"
                size="sm"
                className="ml-3 shrink-0 self-center"
                onClick={() => setPendingDelete(m.memory_id)}
              >
                Delete
              </Button>
            </li>
          ))}
        </ul>

        {nextCursor && (
          <div className="text-center mt-4">
            <Button variant="secondary" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? "Loading…" : "Load more"}
            </Button>
          </div>
        )}
      </div>

      {/* Side form */}
      {(creating || editing) && (
        <div className="w-[360px]">
          <Card>
            <h3 className="mb-4 text-base font-semibold">
              {creating ? "New Memory" : `Edit: ${editing.key}`}
            </h3>
            <form onSubmit={creating ? handleCreate : handleUpdate}>
              {creating && (
                <div className="mb-3">
                  <Label htmlFor="memory-key">Key</Label>
                  <Input
                    id="memory-key"
                    required
                    value={form.key}
                    onChange={(e) => setForm({ ...form, key: e.target.value })}
                    placeholder="unique-key"
                  />
                </div>
              )}
              <div className="mb-3">
                <Label htmlFor="memory-value">Value</Label>
                <Textarea
                  id="memory-value"
                  required
                  rows={6}
                  value={form.value}
                  onChange={(e) => setForm({ ...form, value: e.target.value })}
                  placeholder="Memory content…"
                />
              </div>
              <div className="mb-4">
                <Label htmlFor="memory-tags">Tags (comma-separated)</Label>
                <Input
                  id="memory-tags"
                  value={form.tags}
                  onChange={(e) => setForm({ ...form, tags: e.target.value })}
                  placeholder="tag1, tag2"
                />
              </div>
              <div className="flex gap-2">
                <Button type="submit">Save</Button>
                <Button variant="secondary" type="button" onClick={closePanel}>
                  Cancel
                </Button>
              </div>
            </form>
          </Card>
        </div>
      )}
    </div>
  );
}
