// Copyright (c) 2026 John Carter. All rights reserved.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api.js";

describe("api", () => {
  let fetchMock;

  let storage;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    storage = {};
    vi.stubGlobal("localStorage", {
      getItem: (k) => storage[k] ?? null,
      setItem: (k, v) => { storage[k] = v; },
      removeItem: (k) => { delete storage[k]; },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockOk(body, status = 200) {
    fetchMock.mockResolvedValue({
      ok: true,
      status,
      json: () => Promise.resolve(body),
    });
  }

  function mockErr(detail, status = 400) {
    fetchMock.mockResolvedValue({
      ok: false,
      status,
      statusText: "Bad Request",
      json: () => Promise.resolve(detail !== undefined ? { detail } : {}),
    });
  }

  // ---------------------------------------------------------------------------
  // request() core behaviour
  // ---------------------------------------------------------------------------

  it("adds Authorization header when token is in localStorage", async () => {
    localStorage.setItem("hive_mgmt_token", "tok123");
    mockOk({ items: [] });
    await api.listMemories();
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer tok123");
  });

  it("omits Authorization header when no token", async () => {
    mockOk({ items: [] });
    await api.listMemories();
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it("sends JSON body on POST requests", async () => {
    mockOk({ memory_id: "1", key: "k", value: "v", tags: [] });
    await api.createMemory({ key: "k", value: "v", tags: [] });
    const call = fetchMock.mock.calls[0];
    expect(call[1].method).toBe("POST");
    expect(call[1].body).toBe(JSON.stringify({ key: "k", value: "v", tags: [] }));
  });

  it("omits body on GET requests", async () => {
    mockOk({ items: [] });
    await api.listMemories();
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined();
  });

  it("throws error with detail on non-ok response", async () => {
    mockErr("Something bad");
    await expect(api.listMemories()).rejects.toThrow("Something bad");
  });

  it("falls back to statusText when error json has no detail", async () => {
    mockErr(undefined);
    await expect(api.listMemories()).rejects.toThrow("Request failed");
  });

  it("falls back to statusText when error json parse fails", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: () => Promise.reject(new Error("parse fail")),
    });
    await expect(api.listMemories()).rejects.toThrow("Internal Server Error");
  });

  it("returns null on 204 response", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204 });
    const result = await api.deleteMemory("id1");
    expect(result).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // listMemories
  // ---------------------------------------------------------------------------

  it("listMemories without tag or cursor", async () => {
    mockOk({ items: [] });
    await api.listMemories();
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/memories\?limit=50/);
    expect(fetchMock.mock.calls[0][0]).not.toContain("tag=");
    expect(fetchMock.mock.calls[0][0]).not.toContain("cursor=");
  });

  it("listMemories with tag", async () => {
    mockOk({ items: [] });
    await api.listMemories("mytag");
    expect(fetchMock.mock.calls[0][0]).toContain("tag=mytag");
  });

  it("listMemories with cursor", async () => {
    mockOk({ items: [] });
    await api.listMemories(undefined, { cursor: "abc123" });
    expect(fetchMock.mock.calls[0][0]).toContain("cursor=abc123");
  });

  it("listMemories with custom limit", async () => {
    mockOk({ items: [] });
    await api.listMemories(undefined, { limit: 10 });
    expect(fetchMock.mock.calls[0][0]).toContain("limit=10");
  });

  // ---------------------------------------------------------------------------
  // Memory CRUD
  // ---------------------------------------------------------------------------

  it("getMemory calls correct endpoint", async () => {
    mockOk({ memory_id: "m1" });
    await api.getMemory("m1");
    expect(fetchMock.mock.calls[0][0]).toContain("/api/memories/m1");
    expect(fetchMock.mock.calls[0][1].method).toBe("GET");
  });

  it("updateMemory sends PATCH with body", async () => {
    mockOk({ memory_id: "m1", value: "new" });
    await api.updateMemory("m1", { value: "new" });
    const call = fetchMock.mock.calls[0];
    expect(call[0]).toContain("/api/memories/m1");
    expect(call[1].method).toBe("PATCH");
    expect(JSON.parse(call[1].body)).toEqual({ value: "new" });
  });

  it("deleteMemory calls DELETE", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204 });
    await api.deleteMemory("m2");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
    expect(fetchMock.mock.calls[0][0]).toContain("/api/memories/m2");
  });

  // ---------------------------------------------------------------------------
  // listClients
  // ---------------------------------------------------------------------------

  it("listClients without cursor", async () => {
    mockOk({ items: [] });
    await api.listClients();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/clients");
    expect(fetchMock.mock.calls[0][0]).not.toContain("cursor=");
  });

  it("listClients with cursor", async () => {
    mockOk({ items: [] });
    await api.listClients({ cursor: "tok" });
    expect(fetchMock.mock.calls[0][0]).toContain("cursor=tok");
  });

  // ---------------------------------------------------------------------------
  // Client CRUD
  // ---------------------------------------------------------------------------

  it("getClient calls correct endpoint", async () => {
    mockOk({ client_id: "c1" });
    await api.getClient("c1");
    expect(fetchMock.mock.calls[0][0]).toContain("/api/clients/c1");
  });

  it("createClient sends POST with body", async () => {
    mockOk({ client_id: "c1" });
    await api.createClient({ client_name: "App" });
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ client_name: "App" });
  });

  it("deleteClient calls DELETE", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204 });
    await api.deleteClient("c2");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
    expect(fetchMock.mock.calls[0][0]).toContain("/api/clients/c2");
  });

  // ---------------------------------------------------------------------------
  // Stats & Activity
  // ---------------------------------------------------------------------------

  it("getStats calls /api/stats", async () => {
    mockOk({ total_memories: 5 });
    await api.getStats();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/stats");
  });

  it("getActivity with default params", async () => {
    mockOk({ items: [] });
    await api.getActivity();
    expect(fetchMock.mock.calls[0][0]).toContain("days=7");
    expect(fetchMock.mock.calls[0][0]).toContain("limit=100");
  });

  it("getActivity with custom params", async () => {
    mockOk({ items: [] });
    await api.getActivity(30, { limit: 50 });
    expect(fetchMock.mock.calls[0][0]).toContain("days=30");
    expect(fetchMock.mock.calls[0][0]).toContain("limit=50");
  });

  // ---------------------------------------------------------------------------
  // Users
  // ---------------------------------------------------------------------------

  it("getMe calls /api/users/me", async () => {
    mockOk({ user_id: "u1", email: "u@example.com", role: "user" });
    await api.getMe();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/users/me");
    expect(fetchMock.mock.calls[0][1].method).toBe("GET");
  });

  it("listUsers calls /api/users", async () => {
    mockOk({ items: [] });
    await api.listUsers();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/users");
    expect(fetchMock.mock.calls[0][0]).not.toContain("/me");
  });

  it("listUsers passes cursor when provided", async () => {
    mockOk({ items: [] });
    await api.listUsers({ cursor: "c123" });
    expect(fetchMock.mock.calls[0][0]).toContain("cursor=c123");
  });

  it("deleteUser calls DELETE /api/users/{id}", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204 });
    await api.deleteUser("u99");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
    expect(fetchMock.mock.calls[0][0]).toContain("/api/users/u99");
  });

  // ---------------------------------------------------------------------------
  // Admin
  // ---------------------------------------------------------------------------

  it("getMetrics calls GET /api/admin/metrics with default period", async () => {
    mockOk({ period: "24h", metrics: {} });
    await api.getMetrics();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/admin/metrics?period=24h");
  });

  it("getMetrics passes custom period", async () => {
    mockOk({ period: "7d", metrics: {} });
    await api.getMetrics("7d");
    expect(fetchMock.mock.calls[0][0]).toContain("period=7d");
  });

  it("getCosts calls GET /api/admin/costs", async () => {
    mockOk({ monthly: [] });
    await api.getCosts();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/admin/costs");
  });

  // ---------------------------------------------------------------------------
  // 401 handling — clears token and redirects
  // ---------------------------------------------------------------------------

  it("401 response clears mgmt token and redirects to /", async () => {
    storage["hive_mgmt_token"] = "old-token";
    vi.stubGlobal("location", { replace: vi.fn() });
    fetchMock.mockResolvedValue({ ok: false, status: 401, json: () => Promise.resolve({}) });
    const result = await api.getStats();
    expect(result).toBeNull();
    expect(storage["hive_mgmt_token"]).toBeUndefined();
    expect(window.location.replace).toHaveBeenCalledWith("/");
  });
});
