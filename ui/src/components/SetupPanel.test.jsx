// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SetupPanel from "./SetupPanel.jsx";

describe("SetupPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
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

  it("renders Claude Code and Claude Desktop tabs", async () => {
    await act(async () => render(<SetupPanel />));
    expect(screen.getByText("Claude Code")).toBeTruthy();
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
});
