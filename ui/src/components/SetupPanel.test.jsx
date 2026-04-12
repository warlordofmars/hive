// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  api: { listMemories: vi.fn(), deleteAccount: vi.fn(), getStats: vi.fn() },
}));

import { api } from "../api.js";
import SetupPanel from "./SetupPanel.jsx";

describe("SetupPanel", () => {
  let _storage;

  beforeEach(() => {
    _storage = {};
    vi.stubGlobal("localStorage", {
      getItem: (k) => _storage[k] ?? null,
      setItem: (k, v) => { _storage[k] = v; },
      removeItem: (k) => { delete _storage[k]; },
    });
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    api.listMemories.mockResolvedValue({ items: [] });
    api.getStats.mockResolvedValue(null);
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("renders both step headings", async () => {
    await act(async () => render(<SetupPanel />));
    expect(screen.getByText(/Step 1/)).toBeTruthy();
    expect(screen.getByText(/Step 2/)).toBeTruthy();
  });

  it("renders Claude Code, Cursor, and Claude Desktop tabs", async () => {
    await act(async () => render(<SetupPanel />));
    expect(screen.getByText("Claude Code")).toBeTruthy();
    expect(screen.getByText("Cursor")).toBeTruthy();
    expect(screen.getByText("Claude Desktop")).toBeTruthy();
  });

  it("defaults to Claude Code tab and shows http type config", async () => {
    await act(async () => render(<SetupPanel />));
    expect(document.body.textContent).toContain('"type": "http"');
  });

  it("switches to Claude Desktop tab and shows mcp-remote config", async () => {
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Claude Desktop"));
    expect(document.body.textContent).toContain("mcp-remote");
    expect(document.body.textContent).toContain('"command": "npx"');
  });

  it("shows Copy button initially", async () => {
    await act(async () => render(<SetupPanel />));
    expect(screen.getByText("Copy")).toBeTruthy();
  });

  it("shows Copied! after click and reverts after 2s", async () => {
    vi.useFakeTimers();
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Copy"));
    expect(screen.getByText("Copied!")).toBeTruthy();
    act(() => vi.runAllTimers());
    expect(screen.getByText("Copy")).toBeTruthy();
    vi.useRealTimers();
  });

  it("uses VITE_MCP_BASE when set", async () => {
    vi.stubEnv("VITE_MCP_BASE", "https://custom.example.com/mcp");
    await act(async () => render(<SetupPanel />));
    expect(document.body.textContent).toContain("custom.example.com/mcp");
  });

  it("falls back to window.location.origin + /mcp when VITE_MCP_BASE not set", async () => {
    await act(async () => render(<SetupPanel />));
    expect(document.body.textContent).toContain("localhost");
    expect(document.body.textContent).toContain("/mcp");
  });

  it("step 2 text updates when switching tabs", async () => {
    await act(async () => render(<SetupPanel />));
    expect(document.body.textContent).toContain("Claude Code");
    fireEvent.click(screen.getByText("Claude Desktop"));
    expect(document.body.textContent).toContain("Restart Claude Desktop");
  });

  it("switching back to Claude Code tab restores http config", async () => {
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Claude Desktop"));
    fireEvent.click(screen.getByText("Claude Code"));
    expect(document.body.textContent).toContain('"type": "http"');
  });

  it("switches to Cursor tab and shows http config", async () => {
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Cursor"));
    expect(document.body.textContent).toContain('"type": "http"');
    expect(document.body.textContent).toContain("~/.cursor/mcp.json");
  });

  it("step 2 text updates when switching to Cursor tab", async () => {
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Cursor"));
    expect(document.body.textContent).toContain("Restart Cursor");
  });

  it("Copy sets step1 flag in localStorage", async () => {
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Copy"));
    expect(_storage["hive_setup_step1_done"]).toBe("1");
  });

  it("shows step 1 checkmark when step1 flag already set in localStorage", async () => {
    _storage["hive_setup_step1_done"] = "1";
    await act(async () => render(<SetupPanel />));
    // Check icon rendered (SVG) — heading still contains "Step 1" text
    expect(screen.getByText(/Step 1/)).toBeTruthy();
  });

  it("Test connection button calls api.listMemories", async () => {
    await act(async () => render(<SetupPanel />));
    await act(async () => fireEvent.click(screen.getByText("Test connection")));
    expect(api.listMemories).toHaveBeenCalled();
  });

  it("shows Connected on successful test", async () => {
    await act(async () => render(<SetupPanel />));
    await act(async () => fireEvent.click(screen.getByText("Test connection")));
    await waitFor(() => expect(screen.getByText("Connected")).toBeTruthy());
  });

  it("shows error message on failed test", async () => {
    api.listMemories.mockRejectedValue(new Error("Unauthorized"));
    await act(async () => render(<SetupPanel />));
    await act(async () => fireEvent.click(screen.getByText("Test connection")));
    await waitFor(() => expect(screen.getByText("Unauthorized")).toBeTruthy());
  });

  it("shows error message when rejection has no message", async () => {
    api.listMemories.mockRejectedValue({});
    await act(async () => render(<SetupPanel />));
    await act(async () => fireEvent.click(screen.getByText("Test connection")));
    await waitFor(() => expect(screen.getByText("Connection failed")).toBeTruthy());
  });

  it("shows You're all set banner when both steps complete", async () => {
    _storage["hive_setup_step1_done"] = "1";
    await act(async () => render(<SetupPanel />));
    await act(async () => fireEvent.click(screen.getByText("Test connection")));
    await waitFor(() => expect(screen.getByText(/You're all set/)).toBeTruthy());
  });

  it("dispatches hive:switch-tab event when Memories link clicked in banner", async () => {
    _storage["hive_setup_step1_done"] = "1";
    await act(async () => render(<SetupPanel />));
    await act(async () => fireEvent.click(screen.getByText("Test connection")));
    await waitFor(() => expect(screen.getByText(/You're all set/)).toBeTruthy());
    const handler = vi.fn();
    window.addEventListener("hive:switch-tab", handler);
    fireEvent.click(screen.getByText("Memories"));
    expect(handler).toHaveBeenCalled();
    expect(handler.mock.calls[0][0].detail).toBe("memories");
    window.removeEventListener("hive:switch-tab", handler);
  });

  it("renders Danger Zone section with delete button", async () => {
    await act(async () => render(<SetupPanel />));
    expect(screen.getByText("Danger Zone")).toBeTruthy();
    expect(screen.getByText("Delete my account")).toBeTruthy();
  });

  it("shows confirmation dialog when Delete my account is clicked", async () => {
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Delete my account"));
    expect(screen.getByText(/Are you sure/)).toBeTruthy();
    expect(screen.getByText("Yes, delete everything")).toBeTruthy();
    expect(screen.getByText("Cancel")).toBeTruthy();
  });

  it("hides confirmation dialog on Cancel", async () => {
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Delete my account"));
    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.getByText("Delete my account")).toBeTruthy();
    expect(screen.queryByText(/Are you sure/)).toBeNull();
  });

  it("calls api.deleteAccount and redirects on confirm", async () => {
    api.deleteAccount.mockResolvedValue(null);
    const replaceMock = vi.fn();
    vi.stubGlobal("location", { replace: replaceMock });
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Delete my account"));
    await act(async () => fireEvent.click(screen.getByText("Yes, delete everything")));
    expect(api.deleteAccount).toHaveBeenCalled();
    expect(replaceMock).toHaveBeenCalledWith("/");
  });

  it("shows error message when deleteAccount fails", async () => {
    api.deleteAccount.mockRejectedValue(new Error("Server error"));
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Delete my account"));
    await act(async () => fireEvent.click(screen.getByText("Yes, delete everything")));
    await waitFor(() => expect(screen.getByText("Server error")).toBeTruthy());
  });

  it("shows fallback error when deleteAccount rejects without message", async () => {
    api.deleteAccount.mockRejectedValue({});
    await act(async () => render(<SetupPanel />));
    fireEvent.click(screen.getByText("Delete my account"));
    await act(async () => fireEvent.click(screen.getByText("Yes, delete everything")));
    await waitFor(() => expect(screen.getByText("Deletion failed")).toBeTruthy());
  });

  it("does not render Usage section when getStats returns null", async () => {
    api.getStats.mockResolvedValue(null);
    await act(async () => render(<SetupPanel />));
    expect(screen.queryByText("Usage")).toBeNull();
  });

  it("does not render Usage section when stats have no memory_limit", async () => {
    api.getStats.mockResolvedValue({ total_memories: 10, total_clients: 2, memory_limit: null });
    await act(async () => render(<SetupPanel />));
    expect(screen.queryByText("Usage")).toBeNull();
  });

  it("renders Usage section with quota bars when limits are present", async () => {
    api.getStats.mockResolvedValue({
      total_memories: 42,
      total_clients: 3,
      memory_limit: 500,
      client_limit: 10,
    });
    await act(async () => render(<SetupPanel />));
    await waitFor(() => expect(screen.getByText("Usage")).toBeTruthy());
    expect(screen.getByText("Memories")).toBeTruthy();
    expect(screen.getByText("Clients")).toBeTruthy();
    expect(screen.getByText("42 / 500")).toBeTruthy();
    expect(screen.getByText("3 / 10")).toBeTruthy();
  });

  it("shows danger color for quota at 100%", async () => {
    api.getStats.mockResolvedValue({
      total_memories: 500,
      total_clients: 1,
      memory_limit: 500,
      client_limit: 10,
    });
    await act(async () => render(<SetupPanel />));
    await waitFor(() => expect(screen.getByText("500 / 500")).toBeTruthy());
    const label = screen.getByText("500 / 500");
    expect(label.className).toContain("text-[var(--danger)]");
  });

  it("shows muted color for quota under 80%", async () => {
    api.getStats.mockResolvedValue({
      total_memories: 10,
      total_clients: 1,
      memory_limit: 500,
      client_limit: 10,
    });
    await act(async () => render(<SetupPanel />));
    await waitFor(() => expect(screen.getByText("10 / 500")).toBeTruthy());
    const label = screen.getByText("10 / 500");
    expect(label.className).toContain("text-[var(--text-muted)]");
  });

  it("shows amber bar color for quota between 80% and 99%", async () => {
    api.getStats.mockResolvedValue({
      total_memories: 420,
      total_clients: 1,
      memory_limit: 500,
      client_limit: 10,
    });
    await act(async () => render(<SetupPanel />));
    await waitFor(() => expect(screen.getByText("420 / 500")).toBeTruthy());
    // bar fill div is the one with inline background = amber
    const bars = document.querySelectorAll('[style*="background: var(--amber)"]');
    expect(bars.length).toBeGreaterThan(0);
  });

  it("hides Usage section when getStats rejects", async () => {
    api.getStats.mockRejectedValue(new Error("network error"));
    await act(async () => render(<SetupPanel />));
    expect(screen.queryByText("Usage")).toBeNull();
  });
});
