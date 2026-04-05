// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  api: {
    listUsers: vi.fn(),
    deleteUser: vi.fn(),
  },
}));

import { api } from "../api.js";
import UsersPanel from "./UsersPanel.jsx";

const SAMPLE_USERS = [
  {
    user_id: "u1",
    email: "alice@example.com",
    role: "admin",
    last_login_at: "2026-04-01T12:00:00Z",
  },
  {
    user_id: "u2",
    email: "bob@example.com",
    role: "user",
    last_login_at: "2026-04-02T08:30:00Z",
  },
];

describe("UsersPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows loading state initially", async () => {
    api.listUsers.mockReturnValue(new Promise(() => {}));
    render(<UsersPanel />);
    expect(screen.getByText("Loading…")).toBeTruthy();
  });

  it("renders user rows after loading", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    await act(async () => render(<UsersPanel />));
    expect(screen.getByText("alice@example.com")).toBeTruthy();
    expect(screen.getByText("bob@example.com")).toBeTruthy();
    expect(screen.getByText("admin")).toBeTruthy();
    expect(screen.getByText("user")).toBeTruthy();
  });

  it("shows empty state when no users", async () => {
    api.listUsers.mockResolvedValue({ items: [] });
    await act(async () => render(<UsersPanel />));
    expect(screen.getByText("No users found.")).toBeTruthy();
  });

  it("shows error when listUsers fails", async () => {
    api.listUsers.mockRejectedValue(new Error("Forbidden"));
    await act(async () => render(<UsersPanel />));
    expect(screen.getByText("Forbidden")).toBeTruthy();
  });

  it("deletes user on confirm and removes row", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.deleteUser.mockResolvedValue(null);
    await act(async () => render(<UsersPanel />));

    const deleteButtons = screen.getAllByText("Delete");
    await act(async () => fireEvent.click(deleteButtons[0]));

    expect(api.deleteUser).toHaveBeenCalledWith("u1");
    await waitFor(() => expect(screen.queryByText("alice@example.com")).toBeNull());
  });

  it("does not delete when confirm is cancelled", async () => {
    vi.stubGlobal("confirm", vi.fn(() => false));
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    await act(async () => render(<UsersPanel />));

    const deleteButtons = screen.getAllByText("Delete");
    await act(async () => fireEvent.click(deleteButtons[0]));

    expect(api.deleteUser).not.toHaveBeenCalled();
    expect(screen.getByText("alice@example.com")).toBeTruthy();
  });

  it("shows error when delete fails", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.deleteUser.mockRejectedValue(new Error("Delete failed"));
    await act(async () => render(<UsersPanel />));

    const deleteButtons = screen.getAllByText("Delete");
    await act(async () => fireEvent.click(deleteButtons[0]));

    await waitFor(() => expect(screen.getByText("Delete failed")).toBeTruthy());
  });

  it("renders the Users heading", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    await act(async () => render(<UsersPanel />));
    expect(screen.getByText("Users")).toBeTruthy();
  });
});
