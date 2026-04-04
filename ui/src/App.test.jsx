// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";

vi.mock("./components/MemoryBrowser.jsx", () => ({
  default: () => <div data-testid="memory-browser" />,
}));
vi.mock("./components/ClientManager.jsx", () => ({
  default: () => <div data-testid="client-manager" />,
}));
vi.mock("./components/ActivityLog.jsx", () => ({
  default: () => <div data-testid="activity-log" />,
}));

describe("App", () => {
  let _storage;

  beforeEach(() => {
    _storage = {};
    vi.stubGlobal("localStorage", {
      getItem: (k) => _storage[k] ?? null,
      setItem: (k, v) => { _storage[k] = v; },
      removeItem: (k) => { delete _storage[k]; },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ status: "ok", version: "1.2.3" }),
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders header with Hive title", async () => {
    await act(async () => render(<App />));
    expect(screen.getByText("Hive")).toBeTruthy();
  });

  it("renders all three tab buttons", async () => {
    await act(async () => render(<App />));
    expect(screen.getByText("Memories")).toBeTruthy();
    expect(screen.getByText("OAuth Clients")).toBeTruthy();
    expect(screen.getByText("Activity Log")).toBeTruthy();
  });

  it("shows MemoryBrowser on initial render", async () => {
    await act(async () => render(<App />));
    expect(screen.getByTestId("memory-browser")).toBeTruthy();
    expect(screen.queryByTestId("client-manager")).toBeNull();
    expect(screen.queryByTestId("activity-log")).toBeNull();
  });

  it("switches to ClientManager when OAuth Clients tab is clicked", async () => {
    await act(async () => render(<App />));
    fireEvent.click(screen.getByText("OAuth Clients"));
    expect(screen.getByTestId("client-manager")).toBeTruthy();
    expect(screen.queryByTestId("memory-browser")).toBeNull();
  });

  it("switches to ActivityLog when Activity Log tab is clicked", async () => {
    await act(async () => render(<App />));
    fireEvent.click(screen.getByText("Activity Log"));
    expect(screen.getByTestId("activity-log")).toBeTruthy();
    expect(screen.queryByTestId("memory-browser")).toBeNull();
  });

  it("token input saves to localStorage and state", async () => {
    await act(async () => render(<App />));
    const input = screen.getByPlaceholderText("Bearer token");
    fireEvent.change(input, { target: { value: "mytoken" } });
    expect(localStorage.getItem("hive_token")).toBe("mytoken");
    expect(input.value).toBe("mytoken");
  });

  it("pre-fills token from localStorage", async () => {
    localStorage.setItem("hive_token", "stored-tok");
    await act(async () => render(<App />));
    expect(screen.getByPlaceholderText("Bearer token").value).toBe("stored-tok");
  });

  it("shows version in footer after health check", async () => {
    await act(async () => render(<App />));
    await waitFor(() => expect(screen.getByText("Hive 1.2.3")).toBeTruthy());
  });

  it("hides footer when health check returns no version", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ status: "ok" }),
      }),
    );
    await act(async () => render(<App />));
    await waitFor(() => {});
    expect(screen.queryByText(/Hive \d/)).toBeNull();
  });

  it("does not crash when health check fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    await act(async () => render(<App />));
    // Should still render tabs without crashing
    expect(screen.getByText("Memories")).toBeTruthy();
    expect(screen.queryByText(/Hive \d/)).toBeNull();
  });
});
