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
vi.mock("./components/UsersPanel.jsx", () => ({
  default: () => <div data-testid="users-panel" />,
}));

/** Build a syntactically-valid mgmt JWT with given claims. */
function makeToken({ expOffsetSeconds = 3600, role = "user", email = "u@example.com" } = {}) {
  const exp = Math.floor(Date.now() / 1000) + expOffsetSeconds;
  const payload = btoa(JSON.stringify({ exp, sub: "test-user", role, email }));
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
    _storage["hive_mgmt_token"] = makeToken();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders header with Hive title", async () => {
    await act(async () => render(<App />));
    expect(screen.getByText("Hive")).toBeTruthy();
  });

  it("renders the three base tab buttons for non-admin", async () => {
    await act(async () => render(<App />));
    expect(screen.getByText("Memories")).toBeTruthy();
    expect(screen.getByText("OAuth Clients")).toBeTruthy();
    expect(screen.getByText("Activity Log")).toBeTruthy();
    expect(screen.queryByText("Users")).toBeNull();
  });

  it("renders Users tab for admin", async () => {
    _storage["hive_mgmt_token"] = makeToken({ role: "admin" });
    await act(async () => render(<App />));
    expect(screen.getByText("Users")).toBeTruthy();
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

  it("switches to UsersPanel when Users tab is clicked (admin only)", async () => {
    _storage["hive_mgmt_token"] = makeToken({ role: "admin" });
    await act(async () => render(<App />));
    fireEvent.click(screen.getByText("Users"));
    expect(screen.getByTestId("users-panel")).toBeTruthy();
    expect(screen.queryByTestId("memory-browser")).toBeNull();
  });

  it("shows LoginPage when no token is stored", async () => {
    delete _storage["hive_mgmt_token"];
    await act(async () => render(<App />));
    expect(screen.getByTestId("login-page")).toBeTruthy();
    expect(screen.queryByTestId("memory-browser")).toBeNull();
  });

  it("shows LoginPage when token is expired", async () => {
    _storage["hive_mgmt_token"] = makeToken({ expOffsetSeconds: -3600 });
    await act(async () => render(<App />));
    expect(screen.getByTestId("login-page")).toBeTruthy();
  });

  it("shows LoginPage when token is malformed", async () => {
    _storage["hive_mgmt_token"] = "not.a.jwt";
    await act(async () => render(<App />));
    expect(screen.getByTestId("login-page")).toBeTruthy();
  });

  it("displays user email in header", async () => {
    _storage["hive_mgmt_token"] = makeToken({ email: "alice@example.com" });
    await act(async () => render(<App />));
    expect(screen.getByText("alice@example.com")).toBeTruthy();
  });

  it("does not show email when token has no email claim", async () => {
    _storage["hive_mgmt_token"] = makeToken({ email: null });
    await act(async () => render(<App />));
    // email span is rendered with "" so it's not visible — just confirm no crash
    expect(screen.getByText("Hive")).toBeTruthy();
  });

  it("sign out button clears mgmt token and reloads", async () => {
    const replaceMock = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace: replaceMock });
    await act(async () => render(<App />));
    fireEvent.click(screen.getByText("Sign out"));
    expect(_storage["hive_mgmt_token"]).toBeUndefined();
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
