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
vi.mock("./components/LoginPage.jsx", () => ({
  default: () => <div data-testid="login-page" />,
}));
vi.mock("./components/AuthCallback.jsx", () => ({
  default: () => <div data-testid="auth-callback" />,
}));

/** Build a syntactically-valid JWT with the given exp (seconds from epoch). */
function makeToken(expOffsetSeconds = 3600) {
  const exp = Math.floor(Date.now() / 1000) + expOffsetSeconds;
  const payload = btoa(JSON.stringify({ exp, sub: "test-client" }));
  return `eyJhbGciOiJIUzI1NiJ9.${payload}.sig`;
}

describe("App", () => {
  let _storage;

  beforeEach(() => {
    _storage = {};
    vi.stubGlobal("localStorage", {
      getItem: (k) => _storage[k] ?? null,
      setItem: (k, v) => {
        _storage[k] = v;
      },
      removeItem: (k) => {
        delete _storage[k];
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ status: "ok", version: "1.2.3" }),
      }),
    );
    // Most tests need a valid token — set it by default
    _storage["hive_token"] = makeToken();
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

  it("shows LoginPage when no token is stored", async () => {
    delete _storage["hive_token"];
    await act(async () => render(<App />));
    expect(screen.getByTestId("login-page")).toBeTruthy();
    expect(screen.queryByTestId("memory-browser")).toBeNull();
  });

  it("shows LoginPage when token is expired", async () => {
    _storage["hive_token"] = makeToken(-3600); // expired 1h ago
    await act(async () => render(<App />));
    expect(screen.getByTestId("login-page")).toBeTruthy();
  });

  it("shows LoginPage when token is malformed", async () => {
    _storage["hive_token"] = "not.a.jwt"; // base64 decodes but no exp field
    await act(async () => render(<App />));
    // isTokenValid catches the exception and returns false
    expect(screen.getByTestId("login-page")).toBeTruthy();
  });

  it("sign out button clears token and reloads", async () => {
    const replaceMock = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace: replaceMock });
    await act(async () => render(<App />));
    fireEvent.click(screen.getByText("Sign out"));
    expect(_storage["hive_token"]).toBeUndefined();
    expect(replaceMock).toHaveBeenCalledWith("/");
  });

  it("shows AuthCallback on /oauth/callback route", async () => {
    vi.stubGlobal("location", { ...window.location, pathname: "/oauth/callback" });
    await act(async () => render(<App />));
    expect(screen.getByTestId("auth-callback")).toBeTruthy();
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
    expect(screen.getByText("Memories")).toBeTruthy();
    expect(screen.queryByText(/Hive \d/)).toBeNull();
  });
});
