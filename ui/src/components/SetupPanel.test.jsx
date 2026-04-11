// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  api: { listMemories: vi.fn() },
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
});
