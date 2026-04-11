// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MemoryBrowser, { TagPicker } from "./MemoryBrowser.jsx";

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

// ------------------------------------------------------------------
// TagPicker — isolated unit tests
// ------------------------------------------------------------------

describe("TagPicker", () => {
  const tags = ["alpha", "beta", "gamma"];

  it("renders input when no value is selected", () => {
    render(<TagPicker knownTags={tags} value="" onSelect={vi.fn()} />);
    expect(screen.getByPlaceholderText("Filter by tag")).toBeTruthy();
  });

  it("renders chip when a value is selected", () => {
    render(<TagPicker knownTags={tags} value="alpha" onSelect={vi.fn()} />);
    expect(screen.getByText("alpha")).toBeTruthy();
    expect(screen.queryByPlaceholderText("Filter by tag")).toBeNull();
  });

  it("clear button calls onSelect with empty string", () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="alpha" onSelect={onSelect} />);
    fireEvent.click(screen.getByLabelText("Clear tag filter"));
    expect(onSelect).toHaveBeenCalledWith("");
  });

  it("shows all suggestions on focus", async () => {
    render(<TagPicker knownTags={tags} value="" onSelect={vi.fn()} />);
    fireEvent.focus(screen.getByPlaceholderText("Filter by tag"));
    await waitFor(() => expect(screen.getByRole("listbox")).toBeTruthy());
    expect(screen.getAllByRole("option")).toHaveLength(3);
  });

  it("filters suggestions based on typed input", async () => {
    render(<TagPicker knownTags={tags} value="" onSelect={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText("Filter by tag"), {
      target: { value: "al" },
    });
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "alpha" })).toBeTruthy();
      expect(screen.queryByRole("option", { name: "beta" })).toBeNull();
    });
  });

  it("mousedown on suggestion calls onSelect", async () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    fireEvent.focus(screen.getByPlaceholderText("Filter by tag"));
    await waitFor(() => screen.getByRole("option", { name: "alpha" }));
    fireEvent.mouseDown(screen.getByRole("option", { name: "alpha" }));
    expect(onSelect).toHaveBeenCalledWith("alpha");
  });

  it("ArrowDown highlights next suggestion and cannot go past last", async () => {
    render(<TagPicker knownTags={tags} value="" onSelect={vi.fn()} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.focus(input);
    await waitFor(() => screen.getByRole("option", { name: "alpha" }));

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: "alpha" }).getAttribute("aria-selected")).toBe("true");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: "beta" }).getAttribute("aria-selected")).toBe("true");

    // Past last item — stays on last
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: "gamma" }).getAttribute("aria-selected")).toBe("true");
  });

  it("ArrowUp highlights previous suggestion and cannot go before first", async () => {
    render(<TagPicker knownTags={tags} value="" onSelect={vi.fn()} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.focus(input);
    await waitFor(() => screen.getByRole("option", { name: "alpha" }));

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: "beta" }).getAttribute("aria-selected")).toBe("true");

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(screen.getByRole("option", { name: "alpha" }).getAttribute("aria-selected")).toBe("true");

    // Cannot go before first
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(screen.getByRole("option", { name: "alpha" }).getAttribute("aria-selected")).toBe("true");
  });

  it("Enter with active item selects it", async () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.focus(input);
    await waitFor(() => screen.getByRole("option", { name: "alpha" }));
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("alpha");
  });

  it("Enter with no active item does nothing", async () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.focus(input);
    await waitFor(() => screen.getByRole("option", { name: "alpha" }));
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("Escape when suggestions are open closes the dropdown", async () => {
    render(<TagPicker knownTags={tags} value="" onSelect={vi.fn()} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.focus(input);
    await waitFor(() => screen.getByRole("listbox"));
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
  });

  it("Escape when no suggestions still closes open state", () => {
    render(<TagPicker knownTags={tags} value="" onSelect={vi.fn()} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    // "zzz" has no matches but sets open=true; Escape should close
    fireEvent.change(input, { target: { value: "zzz" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("non-navigation key when no suggestions does nothing", () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.change(input, { target: { value: "zzz" } }); // no matches
    fireEvent.keyDown(input, { key: "a" });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("non-navigation key when dropdown is open does nothing", async () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.focus(input);
    await waitFor(() => screen.getByRole("listbox"));
    fireEvent.keyDown(input, { key: "Tab" });
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("listbox")).toBeTruthy();
  });

  it("blur closes dropdown after delay", async () => {
    render(<TagPicker knownTags={tags} value="" onSelect={vi.fn()} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.focus(input);
    await waitFor(() => screen.getByRole("listbox"));
    fireEvent.blur(input);
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull(), { timeout: 500 });
  });

  it("shows no dropdown when knownTags is empty", () => {
    render(<TagPicker knownTags={[]} value="" onSelect={vi.fn()} />);
    fireEvent.focus(screen.getByPlaceholderText("Filter by tag"));
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});

// ------------------------------------------------------------------
// MemoryBrowser
// ------------------------------------------------------------------

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

  it("passes tag filter to listMemories when a tag is selected", async () => {
    api.listMemories.mockResolvedValue({
      items: [makeMemory({ tags: ["mytag"] })],
      next_cursor: null,
    });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));

    // Type to surface suggestion then select it
    const filterInput = screen.getByPlaceholderText("Filter by tag");
    await act(async () => fireEvent.focus(filterInput));
    await act(async () =>
      fireEvent.change(filterInput, { target: { value: "my" } }),
    );
    await waitFor(() => screen.getByRole("option", { name: "mytag" }));
    await act(async () =>
      fireEvent.mouseDown(screen.getByRole("option", { name: "mytag" })),
    );

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

  // ---------------------------------------------------------------------------
  // List keyboard navigation (#257)
  // ---------------------------------------------------------------------------

  it("ArrowDown moves focus to next card", async () => {
    const m1 = makeMemory({ memory_id: "m1", key: "key1" });
    const m2 = makeMemory({ memory_id: "m2", key: "key2" });
    api.listMemories.mockResolvedValue({ items: [m1, m2], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("key1"));

    const card1 = screen.getByText("key1").closest(".card");
    const card2 = screen.getByText("key2").closest(".card");

    // Focus card1 then press ArrowDown → card2 gets focus
    await act(async () => fireEvent.focus(card1));
    await act(async () => fireEvent.keyDown(card1, { key: "ArrowDown" }));
    await waitFor(() => expect(card2).toHaveFocus());
  });

  it("ArrowUp moves focus to previous card", async () => {
    const m1 = makeMemory({ memory_id: "m1", key: "key1" });
    const m2 = makeMemory({ memory_id: "m2", key: "key2" });
    api.listMemories.mockResolvedValue({ items: [m1, m2], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("key2"));

    const card1 = screen.getByText("key1").closest(".card");
    const card2 = screen.getByText("key2").closest(".card");

    // Focus card2 then press ArrowUp → card1 gets focus
    await act(async () => fireEvent.focus(card2));
    await act(async () => fireEvent.keyDown(card2, { key: "ArrowUp" }));
    await waitFor(() => expect(card1).toHaveFocus());
  });

  it("Delete key on focused card triggers delete", async () => {
    api.listMemories
      .mockResolvedValueOnce({ items: [makeMemory()], next_cursor: null })
      .mockResolvedValue({ items: [], next_cursor: null });
    api.deleteMemory.mockResolvedValue(null);

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    const card = screen.getByText("test-key").closest(".card");
    await act(async () => fireEvent.keyDown(card, { key: "Delete" }));
    expect(api.deleteMemory).toHaveBeenCalledWith("m1");
  });

  it("Backspace key on focused card triggers delete", async () => {
    api.listMemories
      .mockResolvedValueOnce({ items: [makeMemory()], next_cursor: null })
      .mockResolvedValue({ items: [], next_cursor: null });
    api.deleteMemory.mockResolvedValue(null);

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    const card = screen.getByText("test-key").closest(".card");
    await act(async () => fireEvent.keyDown(card, { key: "Backspace" }));
    expect(api.deleteMemory).toHaveBeenCalledWith("m1");
  });

  it("Escape key on card closes the edit panel", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));

    // Open edit panel
    fireEvent.click(screen.getByText("test-key").closest(".card"));
    expect(screen.getByText("Edit: test-key")).toBeTruthy();

    // Escape closes it
    const card = screen.getByText("test-key").closest(".card");
    await act(async () => fireEvent.keyDown(card, { key: "Escape" }));
    expect(screen.queryByText("Edit: test-key")).toBeNull();
  });

  it("onFocus on card tracks focusedIndex (ArrowDown starts from focused card)", async () => {
    const m1 = makeMemory({ memory_id: "m1", key: "key1" });
    const m2 = makeMemory({ memory_id: "m2", key: "key2" });
    const m3 = makeMemory({ memory_id: "m3", key: "key3" });
    api.listMemories.mockResolvedValue({ items: [m1, m2, m3], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("key2"));

    const card2 = screen.getByText("key2").closest(".card");
    const card3 = screen.getByText("key3").closest(".card");

    // Focus card2 (index 1) then ArrowDown → card3 (index 2)
    await act(async () => fireEvent.focus(card2));
    await act(async () => fireEvent.keyDown(card2, { key: "ArrowDown" }));
    await waitFor(() => expect(card3).toHaveFocus());
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

  it("clears tag filter chip when search query is typed", async () => {
    api.listMemories.mockResolvedValue({
      items: [makeMemory({ tags: ["mytag"] })],
      next_cursor: null,
    });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));

    // Select tag via TagPicker
    const filterInput = screen.getByPlaceholderText("Filter by tag");
    await act(async () => fireEvent.focus(filterInput));
    await act(async () =>
      fireEvent.change(filterInput, { target: { value: "my" } }),
    );
    await waitFor(() => screen.getByRole("option", { name: "mytag" }));
    await act(async () =>
      fireEvent.mouseDown(screen.getByRole("option", { name: "mytag" })),
    );

    // Chip is now shown; input is gone
    expect(screen.queryByPlaceholderText("Filter by tag")).toBeNull();

    // Type in search — tag chip should clear (input reappears)
    const searchInput = screen.getByPlaceholderText("Search by meaning…");
    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "query" } }),
    );
    expect(screen.getByPlaceholderText("Filter by tag")).toBeTruthy();
  });

  it("clears search query when tag is selected from picker", async () => {
    api.listMemories.mockResolvedValue({
      items: [makeMemory({ tags: ["mytag"] })],
      next_cursor: null,
    });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));

    // Enter search mode
    const searchInput = screen.getByPlaceholderText("Search by meaning…");
    await act(async () =>
      fireEvent.change(searchInput, { target: { value: "query" } }),
    );

    // Select tag via TagPicker
    const filterInput = screen.getByPlaceholderText("Filter by tag");
    await act(async () => fireEvent.focus(filterInput));
    await act(async () =>
      fireEvent.change(filterInput, { target: { value: "my" } }),
    );
    await waitFor(() => screen.getByRole("option", { name: "mytag" }));
    await act(async () =>
      fireEvent.mouseDown(screen.getByRole("option", { name: "mytag" })),
    );

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
