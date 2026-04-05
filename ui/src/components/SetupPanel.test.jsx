// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  api: {
    createClient: vi.fn(),
  },
}));

import { api } from "../api.js";
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

  it("renders all three step headings", async () => {
    await act(async () => render(<SetupPanel />));
    expect(screen.getByText(/Step 1/)).toBeTruthy();
    expect(screen.getByText(/Step 2/)).toBeTruthy();
    expect(screen.getByText(/Step 3/)).toBeTruthy();
  });

  it("renders the registration form initially", async () => {
    await act(async () => render(<SetupPanel />));
    expect(screen.getByPlaceholderText("Client name")).toBeTruthy();
    expect(screen.getByText("Register")).toBeTruthy();
    expect(screen.queryByText(/client ID/)).toBeNull();
  });

  it("shows Registering\u2026 during submit", async () => {
    let resolve;
    api.createClient.mockReturnValue(new Promise((r) => { resolve = r; }));
    await act(async () => render(<SetupPanel />));
    fireEvent.change(screen.getByPlaceholderText("Client name"), {
      target: { value: "My Client" },
    });
    act(() => {
      fireEvent.submit(screen.getByPlaceholderText("Client name").closest("form"));
    });
    expect(screen.getByText("Registering\u2026")).toBeTruthy();
    await act(async () => resolve({ client_id: "c1" }));
  });

  it("shows client_id on successful registration", async () => {
    api.createClient.mockResolvedValue({ client_id: "test-id-123" });
    await act(async () => render(<SetupPanel />));
    fireEvent.change(screen.getByPlaceholderText("Client name"), {
      target: { value: "My Client" },
    });
    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("Client name").closest("form")),
    );
    await waitFor(() => expect(screen.getByText(/test-id-123/)).toBeTruthy());
    expect(screen.queryByPlaceholderText("Client name")).toBeNull();
  });

  it("shows error when registration fails", async () => {
    api.createClient.mockRejectedValue(new Error("Name already taken"));
    await act(async () => render(<SetupPanel />));
    fireEvent.change(screen.getByPlaceholderText("Client name"), {
      target: { value: "Bad" },
    });
    await act(async () =>
      fireEvent.submit(screen.getByPlaceholderText("Client name").closest("form")),
    );
    await waitFor(() => expect(screen.getByText("Name already taken")).toBeTruthy());
    expect(screen.getByPlaceholderText("Client name")).toBeTruthy();
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
});
