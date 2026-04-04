// Copyright (c) 2026 John Carter. All rights reserved.
/**
 * Hive API client — thin wrapper around fetch.
 * Token is read from localStorage.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "";

function getToken() {
  return localStorage.getItem("hive_token") ?? "";
}

async function request(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }

  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // Memories
  listMemories: (tag) =>
    request("GET", `/api/memories${tag ? `?tag=${encodeURIComponent(tag)}` : ""}`),
  getMemory: (id) => request("GET", `/api/memories/${id}`),
  createMemory: (body) => request("POST", "/api/memories", body),
  updateMemory: (id, body) => request("PATCH", `/api/memories/${id}`, body),
  deleteMemory: (id) => request("DELETE", `/api/memories/${id}`),

  // Clients
  listClients: () => request("GET", "/api/clients"),
  getClient: (id) => request("GET", `/api/clients/${id}`),
  createClient: (body) => request("POST", "/api/clients", body),
  deleteClient: (id) => request("DELETE", `/api/clients/${id}`),

  // Stats & Activity
  getStats: () => request("GET", "/api/stats"),
  getActivity: (days = 7) => request("GET", `/api/activity?days=${days}`),
};
