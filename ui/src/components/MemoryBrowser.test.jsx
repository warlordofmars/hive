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
    listMemoryVersions: vi.fn(),
    restoreMemoryVersion: vi.fn(),
    listClients: vi.fn(),
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

  it("Enter with typed value and no suggestions commits the typed value", () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.change(input, { target: { value: "new-tag" } }); // no matches → no suggestions
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("new-tag");
  });

  it("Enter with empty input and no suggestions does nothing", () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.change(input, { target: { value: "zzz" } }); // no matches → no suggestions
    fireEvent.change(input, { target: { value: "" } }); // clear
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("Enter with typed value matching suggestions commits the typed value", () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.change(input, { target: { value: "new-unique-tag" } }); // no match → no suggestions, first branch
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("new-unique-tag");
  });

  it("Enter with typed value matching suggestions (dropdown open) commits typed value", async () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    // Wrap in act so React flushes state (open=true, suggestions populated) before keyDown
    await act(async () => {
      fireEvent.change(input, { target: { value: "alpha" } });
    });
    // Now open=true, suggestions=["alpha"], activeIndex=-1 → second branch (line 64)
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("alpha");
  });

  it("Enter with empty input when suggestions are open does nothing", () => {
    const onSelect = vi.fn();
    render(<TagPicker knownTags={tags} value="" onSelect={onSelect} />);
    const input = screen.getByPlaceholderText("Filter by tag");
    fireEvent.change(input, { target: { value: "tag1" } }); // open suggestions
    fireEvent.change(input, { target: { value: "" } }); // clear input
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
    // Default to a shape without `items` so the `?? []` fallback is exercised.
    api.listClients.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // Helpers
  function getCard() { return screen.getByTestId("memory-card"); }
  function getAllCards() { return screen.getAllByTestId("memory-card"); }

  // ---------------------------------------------------------------------------
  // Initial render
  // ---------------------------------------------------------------------------

  it("renders heading and New button", async () => {
    await act(async () => render(<MemoryBrowser />));
    expect(screen.getByText("Memories")).toBeTruthy();
    expect(screen.getByText("+ New")).toBeTruthy();
  });

  it("toolbar row wraps on narrow screens so the New button stays in view", async () => {
    const { container } = await act(async () => render(<MemoryBrowser />));
    // The heading + search + tag picker + New button share a flex row that
    // must `flex-wrap` (below sm) so the rightmost button doesn't clip when
    // the viewport is 375px.
    const heading = container.querySelector("h2");
    const toolbar = heading.parentElement;
    expect(toolbar.className).toMatch(/flex-wrap/);
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

  it("surfaces a quota banner with a Setup link when createMemory returns 429", async () => {
    const quotaErr = new Error("Memory quota of 500 reached.");
    quotaErr.status = 429;
    api.createMemory.mockRejectedValue(quotaErr);
    const dispatchSpy = vi.spyOn(globalThis, "dispatchEvent");

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

    const banner = await screen.findByTestId("quota-banner");
    expect(banner.textContent).toContain("Quota or rate limit reached");
    expect(banner.textContent).toContain("Memory quota of 500 reached.");
    // Generic error text MUST NOT also surface — banner replaces it.
    expect(screen.queryByText("Memory quota of 500 reached.", { selector: "p" })).toBeNull();

    // Clicking "Open Setup" dispatches the tab-switch event the App
    // shell listens for; banner should clear so it doesn't stick on
    // the new tab.
    fireEvent.click(screen.getByText("Open Setup"));
    const switchEvents = dispatchSpy.mock.calls
      .map((call) => call[0])
      .filter((evt) => evt && evt.type === "hive:switch-tab");
    expect(switchEvents.length).toBeGreaterThan(0);
    expect(switchEvents.at(-1).detail).toBe("setup");
    expect(screen.queryByTestId("quota-banner")).toBeNull();
    dispatchSpy.mockRestore();
  });

  it("clears stale generic error when a follow-up 429 fires", async () => {
    // Sequence: first create fails generically, then a retry hits the
    // quota wall. The banner must take over and the inline error
    // paragraph must clear so the two never render together.
    const genericErr = new Error("Server hiccup");
    const quotaErr = new Error("Memory quota of 500 reached.");
    quotaErr.status = 429;
    api.createMemory.mockRejectedValueOnce(genericErr).mockRejectedValueOnce(quotaErr);

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
    await waitFor(() => expect(screen.getByText("Server hiccup")).toBeTruthy());
    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("unique-key").closest("form")),
    );

    await screen.findByTestId("quota-banner");
    expect(screen.queryByText("Server hiccup")).toBeNull();
  });

  it("clears stale quota banner when a follow-up generic error fires", async () => {
    const quotaErr = new Error("Memory quota of 500 reached.");
    quotaErr.status = 429;
    const genericErr = new Error("Server hiccup");
    api.createMemory.mockRejectedValueOnce(quotaErr).mockRejectedValueOnce(genericErr);

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
    await screen.findByTestId("quota-banner");
    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("unique-key").closest("form")),
    );

    await waitFor(() => expect(screen.getByText("Server hiccup")).toBeTruthy());
    expect(screen.queryByTestId("quota-banner")).toBeNull();
  });

  it("falls back to a generic message on 429 with no detail body", async () => {
    const quotaErr = new Error("");
    quotaErr.status = 429;
    api.createMemory.mockRejectedValue(quotaErr);

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

    const banner = await screen.findByTestId("quota-banner");
    expect(banner.textContent).toContain("Quota or rate limit reached.");
  });

  // ---------------------------------------------------------------------------
  // Edit / Update
  // ---------------------------------------------------------------------------

  it("opens edit form when memory card is clicked", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    fireEvent.click(getCard());
    expect(screen.getByText("Edit: test-key")).toBeTruthy();
    expect(screen.queryByPlaceholderText("unique-key")).toBeNull(); // key field hidden in edit
  });

  it("opens edit form when memory card is activated via keyboard Enter or Space", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    const card = getCard();
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

    const [card1, card2] = getAllCards();

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

    const [card1, card2] = getAllCards();

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
    const card = getCard();
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
    const card = getCard();
    await act(async () => fireEvent.keyDown(card, { key: "Backspace" }));
    expect(api.deleteMemory).toHaveBeenCalledWith("m1");
  });

  it("Escape key on card closes the edit panel", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));

    // Open edit panel
    fireEvent.click(getCard());
    expect(screen.getByText("Edit: test-key")).toBeTruthy();

    // Escape closes it
    const card = getCard();
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

    const [, card2, card3] = getAllCards();

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
    fireEvent.click(getCard());

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
    fireEvent.click(getCard());
    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("Memory content…").closest("form")),
    );
    await waitFor(() => expect(screen.getByText("Update error")).toBeTruthy());
  });

  it("opening create while editing replaces edit panel with create", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    fireEvent.click(getCard());
    expect(screen.getByText("Edit: test-key")).toBeTruthy();
    fireEvent.click(screen.getByText("+ New"));
    expect(screen.getByText("New Memory")).toBeTruthy();
    expect(screen.queryByText("Edit: test-key")).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // Delete
  // ---------------------------------------------------------------------------

  it("opens confirm dialog when Delete button clicked", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("Delete")));
    expect(screen.getByText("Delete this memory?")).toBeTruthy();
  });

  it("deletes memory when confirmed", async () => {
    api.listMemories
      .mockResolvedValueOnce({ items: [makeMemory()], next_cursor: null })
      .mockResolvedValue({ items: [], next_cursor: null });
    api.deleteMemory.mockResolvedValue(null);

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("Delete")));
    await act(async () =>
      fireEvent.click(screen.getAllByText("Delete").at(-1)),
    );
    expect(api.deleteMemory).toHaveBeenCalledWith("m1");
  });

  it("does not delete when dialog is cancelled", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("Delete")));
    await act(async () => fireEvent.click(screen.getByText("Cancel")));
    expect(api.deleteMemory).not.toHaveBeenCalled();
  });

  it("shows error when deleteMemory fails", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.deleteMemory.mockRejectedValue(new Error("Delete failed"));

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("Delete")));
    await act(async () =>
      fireEvent.click(screen.getAllByText("Delete").at(-1)),
    );
    await waitFor(() => expect(screen.getByText("Delete failed")).toBeTruthy());
  });

  it("delete button does not open edit form", async () => {
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

  // ---------------------------------------------------------------------------
  // TTL / expiry
  // ---------------------------------------------------------------------------

  it("shows expiry badge for memories with expires_at", async () => {
    const expiry = new Date("2027-01-15T00:00:00.000Z").toISOString();
    api.listMemories.mockResolvedValue({
      items: [makeMemory({ expires_at: expiry })],
      next_cursor: null,
    });
    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    expect(screen.getByText(/Expires/)).toBeTruthy();
  });

  it("creates memory with TTL when Expires In is set", async () => {
    api.createMemory.mockResolvedValue({ memory_id: "new" });
    api.listMemories
      .mockResolvedValueOnce({ items: [], next_cursor: null })
      .mockResolvedValue({ items: [], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    fireEvent.click(screen.getByText("+ New"));

    fireEvent.change(screen.getByPlaceholderText("unique-key"), {
      target: { value: "ttl-key" },
    });
    fireEvent.change(screen.getByPlaceholderText("Memory content…"), {
      target: { value: "ttl-val" },
    });
    fireEvent.change(screen.getByLabelText("Expires in"), {
      target: { value: "3600" },
    });

    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("unique-key").closest("form")),
    );

    expect(api.createMemory).toHaveBeenCalledWith(
      expect.objectContaining({ ttl_seconds: 3600 }),
    );
  });

  it("updates memory with ttl_seconds 0 to clear TTL when form.ttl is empty", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.updateMemory.mockResolvedValue({});

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    fireEvent.click(getCard());

    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("Memory content…").closest("form")),
    );

    expect(api.updateMemory).toHaveBeenCalledWith(
      "m1",
      expect.objectContaining({ ttl_seconds: 0 }),
    );
  });

  it("updates memory with parsed ttl_seconds when TTL is set", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.updateMemory.mockResolvedValue({});

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    fireEvent.click(getCard());

    fireEvent.change(screen.getByLabelText("Expires in"), {
      target: { value: "86400" },
    });
    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("Memory content…").closest("form")),
    );

    expect(api.updateMemory).toHaveBeenCalledWith(
      "m1",
      expect.objectContaining({ ttl_seconds: 86400 }),
    );
  });

  // ---------------------------------------------------------------------------
  // Version history
  // ---------------------------------------------------------------------------

  it("opens history panel on History button click with no versions", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.listMemoryVersions.mockResolvedValue([]);

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("History")));

    await waitFor(() => expect(screen.getByText("History: test-key")).toBeTruthy());
    expect(screen.getByText("No previous versions.")).toBeTruthy();
  });

  it("shows versions in history panel and truncates long values", async () => {
    const shortVersion = {
      version_timestamp: "20260412T120000000000",
      value: "old value",
      tags: [],
      recorded_at: "2026-04-12T12:00:00.000Z",
    };
    const longVersion = {
      version_timestamp: "20260412T110000000000",
      value: "x".repeat(200),
      tags: [],
      recorded_at: "2026-04-12T11:00:00.000Z",
    };
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.listMemoryVersions.mockResolvedValue([shortVersion, longVersion]);

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("History")));

    await waitFor(() => expect(screen.getByText("old value")).toBeTruthy());
    // Long value gets truncated with ellipsis
    expect(screen.getByText(/x{120}…/)).toBeTruthy();
    expect(screen.getAllByText("Restore")).toHaveLength(2);
  });

  it("restores a version and closes history panel", async () => {
    const version = {
      version_timestamp: "20260412T120000000000",
      value: "old value",
      tags: [],
      recorded_at: "2026-04-12T12:00:00.000Z",
    };
    api.listMemories
      .mockResolvedValueOnce({ items: [makeMemory()], next_cursor: null })
      .mockResolvedValue({ items: [], next_cursor: null });
    api.listMemoryVersions.mockResolvedValue([version]);
    api.restoreMemoryVersion.mockResolvedValue({});

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("History")));
    await waitFor(() => screen.getByText("Restore"));
    await act(async () => fireEvent.click(screen.getByText("Restore")));

    expect(api.restoreMemoryVersion).toHaveBeenCalledWith("m1", "20260412T120000000000");
    await waitFor(() => expect(screen.queryByText("History: test-key")).toBeNull());
  });

  it("shows error when restore fails", async () => {
    const version = {
      version_timestamp: "20260412T120000000000",
      value: "old value",
      tags: [],
      recorded_at: "2026-04-12T12:00:00.000Z",
    };
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.listMemoryVersions.mockResolvedValue([version]);
    api.restoreMemoryVersion.mockRejectedValue(new Error("Restore failed"));

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("History")));
    await waitFor(() => screen.getByText("Restore"));
    await act(async () => fireEvent.click(screen.getByText("Restore")));

    await waitFor(() => expect(screen.getByText("Restore failed")).toBeTruthy());
  });

  it("closes history panel on Close button click", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.listMemoryVersions.mockResolvedValue([]);

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("History")));
    await waitFor(() => screen.getByText("History: test-key"));
    fireEvent.click(screen.getByText("Close"));
    expect(screen.queryByText("History: test-key")).toBeNull();
  });

  it("shows error when listMemoryVersions fails", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.listMemoryVersions.mockRejectedValue(new Error("History load failed"));

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("History")));

    await waitFor(() => expect(screen.getByText("History load failed")).toBeTruthy());
  });

  it("opening create form clears history panel", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.listMemoryVersions.mockResolvedValue([]);
    api.createMemory.mockResolvedValue({ memory_id: "new" });

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("History")));
    await waitFor(() => screen.getByText("History: test-key"));
    fireEvent.click(screen.getByText("+ New"));
    expect(screen.queryByText("History: test-key")).toBeNull();
    expect(screen.getByText("New Memory")).toBeTruthy();
  });

  it("opening edit form clears history panel", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.listMemoryVersions.mockResolvedValue([]);

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    await act(async () => fireEvent.click(screen.getByText("History")));
    await waitFor(() => screen.getByText("History: test-key"));
    fireEvent.click(getCard());
    expect(screen.queryByText("History: test-key")).toBeNull();
    expect(screen.getByText("Edit: test-key")).toBeTruthy();
  });

  it("renders attribution badge with client name when client is known", async () => {
    api.listMemories.mockResolvedValue({
      items: [makeMemory({ owner_client_id: "client-123" })],
      next_cursor: null,
    });
    api.listClients.mockResolvedValue({
      items: [{ client_id: "client-123", client_name: "My Agent" }],
    });

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => expect(screen.getByText("by My Agent")).toBeTruthy());
  });

  it("falls back to client id when name is not yet loaded", async () => {
    api.listMemories.mockResolvedValue({
      items: [makeMemory({ owner_client_id: "client-xyz" })],
      next_cursor: null,
    });
    api.listClients.mockResolvedValue({ items: [] });

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => expect(screen.getByText("by client-xyz")).toBeTruthy());
  });

  it("omits attribution badge when owner_client_id is missing", async () => {
    api.listMemories.mockResolvedValue({
      items: [makeMemory()],
      next_cursor: null,
    });

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
    expect(screen.queryByText(/^by /)).toBeNull();
  });

  it("swallows listClients errors and still renders memories", async () => {
    api.listMemories.mockResolvedValue({ items: [makeMemory()], next_cursor: null });
    api.listClients.mockRejectedValue(new Error("network"));

    await act(async () => render(<MemoryBrowser />));
    await waitFor(() => screen.getByText("test-key"));
  });

  // #537 — Stats charts dispatch `hive:memory-browser` events to deep-link
  // into this component. A tag detail pre-sets the tag filter; a search
  // detail pre-sets the search query (and clears any lingering tag).
  it("hive:memory-browser event with tag pre-filters the list", async () => {
    api.listMemories.mockResolvedValue({ items: [], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    api.listMemories.mockClear();
    await act(async () => {
      globalThis.dispatchEvent(
        new CustomEvent("hive:memory-browser", { detail: { tag: "work" } }),
      );
    });
    await waitFor(() => expect(api.listMemories).toHaveBeenCalledWith("work"));
  });

  it("hive:memory-browser event without a detail payload is a no-op", async () => {
    api.listMemories.mockResolvedValue({ items: [], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    api.listMemories.mockClear();
    await act(async () => {
      // Event with no `detail` at all — covers the `?? {}` fallback so
      // the handler doesn't blow up if dispatched unqualified.
      globalThis.dispatchEvent(new Event("hive:memory-browser"));
    });
    // Neither tag filter nor search ran — no additional list fetches.
    expect(api.listMemories).not.toHaveBeenCalled();
  });

  it("hive:memory-browser event with search pre-sets the search query", async () => {
    api.listMemories.mockResolvedValue({ items: [], next_cursor: null });
    api.searchMemories.mockResolvedValue({ items: [], next_cursor: null });

    await act(async () => render(<MemoryBrowser />));
    await act(async () => {
      globalThis.dispatchEvent(
        new CustomEvent("hive:memory-browser", { detail: { search: "my-key" } }),
      );
    });
    const input = await screen.findByPlaceholderText(/search by meaning/i);
    expect(input.value).toBe("my-key");
  });
});
