// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MemoryBrowser from "./MemoryBrowser.jsx";

vi.mock("../api.js", () => ({
  api: {
    listMemories: vi.fn(),
    searchMemories: vi.fn(),
    createMemory: vi.fn(),
    updateMemory: vi.fn(),
    deleteMemory: vi.fn(),
  },
}));

import { api } from "../api.js";

const makeMemory = (overrides = {}) => ({
  memory_id: "m1",
  key: "test-key",
  value: "test-value",
  tags: ["tag1"],
  ...overrides,
});

describe("MemoryBrowser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listMemories.mockResolvedValue({ items: [], next_cursor: null });
    api.searchMemories.mockResolvedValue({ items: [], count: 0 });
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // ---------------------------------------------------------------------------
  // Initial render
  // ---------------------------------------------------------------------------

  it("renders heading and New button", async () => {
    await act(async () => render(<MemoryBrowser />));
    expect(screen.getByText("Memories")).toBeTruthy();
    expect(screen.getByText("+ New")).toBeTruthy();
  });

  it("renders empty state after load", async () => {
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => expect(screen.getByText("No memories yet")).toBeTruthy());
  });

  it("renders loaded memories", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => expect(screen.getByText("test-key")).toBeTruthy());
    expect(screen.getByText("test-value")).toBeTruthy();
    expect(screen.getByText("tag1")).toBeTruthy();
  });

  it("truncates values longer than 160 characters", async () => {
    const longValue = "x".repeat(200);
    api.listMemories.mockResolvedValue({
      items: [makeMemory({ value: longValue })],
      next_cursor: null,
    });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => expect(screen.getByText(/x{160}…/)).toBeTruthy());
  });

  it("shows error when listMemories fails", async () => {
    api.listMemories.mockRejectedValue(new Error("Load failed"));
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => expect(screen.getByText("Load failed")).toBeTruthy());
  });

  it("passes tag filter to listMemories", async () => {
    await act(async () => render(<MemoryBrowser />));
    const filterInput = screen.getByPlaceholderText("Filter by tag");
    await act(async () => fireEvent.change(filterInput, { target: { value: "mytag" } }));
    await waitFor(() =>
      expect(api.listMemories).toHaveBeenCalledWith("mytag"),
    );
  });

  it("passes undefined tag when filter is empty", async () => {
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() =>
      expect(api.listMemories).toHaveBeenCalledWith(undefined),
    );
  });

  // ---------------------------------------------------------------------------
  // Pagination
  // ---------------------------------------------------------------------------

  it("shows Load more button when next_cursor is set", async () => {
    api.listMemories.mockResolvedValue({
      items: [makeMemory()],
      next_cursor: "cursor1",
    });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => expect(screen.getByText("Load more")).toBeTruthy());
  });

  it("does not show Load more when next_cursor is null", async () => {
    api.listMemories.mockResolvedValue({ items: [], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => {});
    expect(screen.queryByText("Load more")).toBeNull();
  });

  it("loads more memories and appends them", async () => {
    const m1 = makeMemory({ memory_id: "m1", key: "key1" });
    const m2 = makeMemory({ memory_id: "m2", key: "key2" });
    api.listMemories
      .mockResolvedValueOnce({ items: [m1], next_cursor: "cursor1" })
      .mockResolvedValueOnce({ items: [m2], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("Load more"));
    await act(async () => fireEvent.click(screen.getByText("Load more")));
    await waitFor(() => expect(screen.getByText("key2")).toBeTruthy());
    expect(screen.getByText("key1")).toBeTruthy();
  });

  it("shows error when loadMore fails", async () => {
    api.listMemories
      .mockResolvedValueOnce({ items: [makeMemory()], next_cursor: "c1" })
      .mockRejectedValueOnce(new Error("Load more failed"));

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("Load more"));
    await act(async () => fireEvent.click(screen.getByText("Load more")));
    await waitFor(() => expect(screen.getByText("Load more failed")).toBeTruthy());
  });

  // ---------------------------------------------------------------------------
  // Create
  // ---------------------------------------------------------------------------

  it("opens create form on + New click", async () => {
    await act(async () => render(<MemoryBrowser />));
    fireEvent.click(screen.getByText("+ New"));
    expect(screen.getByText("New Memory")).toBeTruthy();
    expect(screen.getByPlaceholderText("unique-key")).toBeTruthy();
  });

  it("closes create form on Cancel", async () => {
    await act(async () => render(<MemoryBrowser />));
    fireEvent.click(screen.getByText("+ New"));
    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.queryByText("New Memory")).toBeNull();
  });

  it("creates memory and closes form on success", async () => {
    api.createMemory.mockResolvedValue({ memory_id: "new" });
    api.listMemories
      .mockResolvedValueOnce({ items: [], next_cursor: null })
      .mockResolvedValue({ items: [], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    fireEvent.click(screen.getByText("+ New"));

    fireEvent.change(screen.getByPlaceholderText("unique-key"), {
      target: { value: "my-key" },
    });
    fireEvent.change(screen.getByPlaceholderText("Memory content…"), {
      target: { value: "my-value" },
    });
    fireEvent.change(screen.getByPlaceholderText("tag1, tag2"), {
      target: { value: "t1, t2" },
    });

    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("unique-key").closest("form")),
    );

    expect(api.createMemory).toHaveBeenCalledWith({
      key: "my-key",
      value: "my-value",
      tags: ["t1", "t2"],
    });
    await waitFor(() => expect(screen.queryByText("New Memory")).toBeNull());
  });

  it("shows error when createMemory fails", async () => {
    api.createMemory.mockRejectedValue(new Error("Create error"));
    await act(async () => render(<MemoryBrowser />));
    fireEvent.click(screen.getByText("+ New"));
    fireEvent.change(screen.getByPlaceholderText("unique-key"), {
      target: { value: "k" },
    });
    fireEvent.change(screen.getByPlaceholderText("Memory content…"), {
      target: { value: "v" },
    });
    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("unique-key").closest("form")),
    );
    await waitFor(() => expect(screen.getByText("Create error")).toBeTruthy());
  });

  // ---------------------------------------------------------------------------
  // Edit / Update
  // ---------------------------------------------------------------------------

  it("opens edit form when memory card is clicked", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    fireEvent.click(screen.getByText("test-key").closest(".card"));
    expect(screen.getByText("Edit: test-key")).toBeTruthy();
    expect(screen.queryByPlaceholderText("unique-key")).toBeNull(); // key field hidden in edit
  });

  it("opens edit form when memory card is activated via keyboard Enter or Space", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    const card = screen.getByText("test-key").closest(".card");
    // Enter opens the form
    fireEvent.keyDown(card, { key: "Enter" });
    expect(screen.getByText("Edit: test-key")).toBeTruthy();
    // Close form; Space also opens it
    fireEvent.click(screen.getByText("Cancel"));
    fireEvent.keyDown(card, { key: " " });
    expect(screen.getByText("Edit: test-key")).toBeTruthy();
    // Other keys are ignored
    fireEvent.click(screen.getByText("Cancel"));
    fireEvent.keyDown(card, { key: "Tab" });
    expect(screen.queryByText("Edit: test-key")).toBeNull();
  });

  it("updates memory and closes form on success", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.updateMemory.mockResolvedValue({});

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    fireEvent.click(screen.getByText("test-key").closest(".card"));

    fireEvent.change(screen.getByPlaceholderText("Memory content…"), {
      target: { value: "new-value" },
    });
    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("Memory content…").closest("form")),
    );

    expect(api.updateMemory).toHaveBeenCalledWith(
      "m1",
      expect.objectContaining({ value: "new-value" }),
    );
    await waitFor(() => expect(screen.queryByText("Edit: test-key")).toBeNull());
  });

  it("shows error when updateMemory fails", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.updateMemory.mockRejectedValue(new Error("Update error"));

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    fireEvent.click(screen.getByText("test-key").closest(".card"));
    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("Memory content…").closest("form")),
    );
    await waitFor(() => expect(screen.getByText("Update error")).toBeTruthy());
  });

  it("opening create while editing replaces edit panel with create", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    fireEvent.click(screen.getByText("test-key").closest(".card"));
    expect(screen.getByText("Edit: test-key")).toBeTruthy();
    fireEvent.click(screen.getByText("+ New"));
    expect(screen.getByText("New Memory")).toBeTruthy();
    expect(screen.queryByText("Edit: test-key")).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // Delete
  // ---------------------------------------------------------------------------

  it("deletes memory when confirmed", async () => {
    api.listMemories
      .mockResolvedValueOnce({ items: [makeMemory()], next_cursor: null })
      .mockResolvedValue({ items: [], next_cursor: null });
    api.deleteMemory.mockResolvedValue(null);

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () =>
      fireEvent.click(screen.getByText("Delete")),
    );
    expect(api.deleteMemory).toHaveBeenCalledWith("m1");
  });

  it("does not delete when confirm is cancelled", async () => {
    vi.stubGlobal("confirm", vi.fn(() => false));
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("Delete")));
    expect(api.deleteMemory).not.toHaveBeenCalled();
  });

  it("shows error when deleteMemory fails", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.deleteMemory.mockRejectedValue(new Error("Delete failed"));

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("Delete")));
    await waitFor(() => expect(screen.getByText("Delete failed")).toBeTruthy());
  });

  it("delete button stops propagation and does not open edit form", async () => {
    vi.stubGlobal("confirm", vi.fn(() => false));
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("Delete")));
    expect(screen.queryByText("Edit: test-key")).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // Semantic search
  // ---------------------------------------------------------------------------

  it("renders Search by meaning input", async () => {
    await act(async () => render(<MemoryBrowser />));
    expect(screen.getByPlaceholderText("Search by meaning…")).toBeTruthy();
  });

  it("calls searchMemories after debounce when query is typed", async () => {
    const m = makeMemory({ memory_id: "s1", key: "semantic-key" });
    api.searchMemories.mockResolvedValue({ items: [m], count: 1 });

    await act(async () => render(<MemoryBrowser />));
    const searchInput = screen.getByPlaceholderText("Search by meaning…");
    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "semantic" } }),
    );
    await waitFor(() => expect(api.searchMemories).toHaveBeenCalledWith("semantic"), {
      timeout: 1000,
    });
  });

  it("renders score badge on search results", async () => {
    const m = makeMemory({ memory_id: "s2", score: 0.87 });
    api.searchMemories.mockResolvedValue({ items: [m], count: 1 });

    await act(async () => render(<MemoryBrowser />));
    const searchInput = screen.getByPlaceholderText("Search by meaning…");
    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "anything" } }),
    );
    await waitFor(() => expect(screen.getByText("87% match")).toBeTruthy(), { timeout: 1000 });
  });

  it("clears tag filter when search query is typed", async () => {
    await act(async () => render(<MemoryBrowser />));
    const tagInput = screen.getByPlaceholderText("Filter by tag");
    const searchInput = screen.getByPlaceholderText("Search by meaning…");

    await act(async () => fireEvent.change(tagInput, { target: { value: "mytag" } }));
    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "query" } }),
    );

    expect(tagInput.value).toBe("");
  });

  it("clears search query when tag filter is typed", async () => {
    await act(async () => render(<MemoryBrowser />));
    const tagInput = screen.getByPlaceholderText("Filter by tag");
    const searchInput = screen.getByPlaceholderText("Search by meaning…");

    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "query" } }),
    );
    await act(async () => fireEvent.change(tagInput, { target: { value: "mytag" } }));

    expect(searchInput.value).toBe("");
  });

  it("does not call searchMemories when search is cleared", async () => {
    await act(async () => render(<MemoryBrowser />));
    const searchInput = screen.getByPlaceholderText("Search by meaning…");

    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "" } }),
    );
    // searchMemories should not be called for empty query
    expect(api.searchMemories).not.toHaveBeenCalled();
  });

  it("clears search mode when search input is cleared", async () => {
    await act(async () => render(<MemoryBrowser />));
    const searchInput = screen.getByPlaceholderText("Search by meaning…");

    // Type something to enter search mode
    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "query" } }),
    );
    // Clear it — should exit search mode (isSearchMode = false)
    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "" } }),
    );
    // Tag filter should still work (list mode re-engaged)
    await waitFor(() =>
      expect(api.listMemories).toHaveBeenCalled(),
    );
  });

  it("shows error when searchMemories fails", async () => {
    api.searchMemories.mockRejectedValue(new Error("Search error"));

    await act(async () => render(<MemoryBrowser />));
    const searchInput = screen.getByPlaceholderText("Search by meaning…");
    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "bad query" } }),
    );
    await waitFor(() => expect(screen.getByText("Search error")).toBeTruthy(), {
      timeout: 1000,
    });
  });
});
