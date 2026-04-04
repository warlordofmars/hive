// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./LoginPage.jsx";

describe("LoginPage", () => {
  let _storage;
  let _session;

  beforeEach(() => {
    _storage = {};
    _session = {};
    vi.stubGlobal("localStorage", {
      getItem: (k) => _storage[k] ?? null,
      setItem: (k, v) => {
        _storage[k] = v;
      },
      removeItem: (k) => {
        delete _storage[k];
      },
    });
    vi.stubGlobal("sessionStorage", {
      getItem: (k) => _session[k] ?? null,
      setItem: (k, v) => {
        _session[k] = v;
      },
      removeItem: (k) => {
        delete _session[k];
      },
    });
    vi.stubGlobal("location", {
      ...window.location,
      origin: "https://hive.example.com",
      href: "",
    });
    vi.stubGlobal("crypto", {
      getRandomValues: (arr) => {
        for (let i = 0; i < arr.length; i++) arr[i] = i % 256;
        return arr;
      },
      subtle: {
        digest: vi.fn().mockResolvedValue(new ArrayBuffer(32)),
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ client_id: "registered-client-id" }),
      }),
    );
    vi.unstubAllGlobals; // reset guard
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the Hive heading and sign-in button", async () => {
    await act(async () => render(<LoginPage />));
    expect(screen.getByText("Hive")).toBeTruthy();
    expect(screen.getByText("Sign in with Google")).toBeTruthy();
  });

  it("renders the tagline", async () => {
    await act(async () => render(<LoginPage />));
    expect(screen.getByText(/Shared persistent memory/)).toBeTruthy();
  });

  it("registers a client and redirects on sign-in click", async () => {
    await act(async () => render(<LoginPage />));
    await act(async () => {
      fireEvent.click(screen.getByText("Sign in with Google"));
    });
    await waitFor(() => {
      expect(_storage["hive_client_id"]).toBe("registered-client-id");
      expect(_session["pkce_verifier"]).toBeTruthy();
      expect(_session["oauth_state"]).toBeTruthy();
    });
  });

  it("skips DCR registration if client_id already stored", async () => {
    _storage["hive_client_id"] = "existing-client";
    await act(async () => render(<LoginPage />));
    await act(async () => {
      fireEvent.click(screen.getByText("Sign in with Google"));
    });
    await waitFor(() => {
      // fetch should not have been called for /oauth/register
      const calls = vi.mocked(fetch).mock.calls;
      const registerCalls = calls.filter(([url]) =>
        typeof url === "string" && url.includes("/oauth/register"),
      );
      expect(registerCalls.length).toBe(0);
    });
  });

  it("shows error message when registration fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }),
    );
    await act(async () => render(<LoginPage />));
    await act(async () => {
      fireEvent.click(screen.getByText("Sign in with Google"));
    });
    await waitFor(() => {
      expect(screen.getByText(/Failed to register UI client/)).toBeTruthy();
    });
  });

  it("shows Redirecting… while loading", async () => {
    // Make fetch hang so loading stays true
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    await act(async () => render(<LoginPage />));
    fireEvent.click(screen.getByText("Sign in with Google"));
    expect(screen.getByText("Redirecting…")).toBeTruthy();
  });
});
