// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  api: {
    listUsers: vi.fn(),
    updateUserRole: vi.fn(),
    getUserStats: vi.fn(),
    deleteUser: vi.fn(),
  },
}));

import { api } from "../api.js";
import UsersPanel from "./UsersPanel.jsx";

const SAMPLE_USERS = [
  {
    user_id: "u1",
    email: "alice@example.com",
    display_name: "Alice",
    role: "admin",
    created_at: "2026-01-01T00:00:00Z",
    last_login_at: "2026-04-01T12:00:00Z",
  },
  {
    user_id: "u2",
    email: "bob@example.com",
    display_name: "Bob",
    role: "user",
    created_at: "2026-02-01T00:00:00Z",
    last_login_at: "2026-04-02T08:30:00Z",
  },
];

describe("UsersPanel", () => {
  afterEach(() => {
    vi.clearAllMocks();
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
  });

  it("shows empty state when no users", async () => {
    api.listUsers.mockResolvedValue({ items: [] });
    await act(async () => render(<UsersPanel />));
    expect(screen.getByText("No users found")).toBeTruthy();
  });

  it("shows error when listUsers fails", async () => {
    api.listUsers.mockRejectedValue(new Error("Forbidden"));
    await act(async () => render(<UsersPanel />));
    expect(screen.getByText("Forbidden")).toBeTruthy();
  });

  it("renders the Users heading", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    await act(async () => render(<UsersPanel />));
    expect(screen.getByText("Users")).toBeTruthy();
  });

  it("shows empty state when listUsers returns null", async () => {
    api.listUsers.mockResolvedValue(null);
    await act(async () => render(<UsersPanel />));
    expect(screen.getByText("No users found")).toBeTruthy();
  });

  it("filters users by email", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    await act(async () => render(<UsersPanel />));
    fireEvent.change(screen.getByTestId("email-search"), { target: { value: "alice" } });
    expect(screen.getByText("alice@example.com")).toBeTruthy();
    expect(screen.queryByText("bob@example.com")).toBeNull();
  });

  it("filters users by role", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    await act(async () => render(<UsersPanel />));
    fireEvent.change(screen.getByTestId("role-filter"), { target: { value: "admin" } });
    expect(screen.getByText("alice@example.com")).toBeTruthy();
    expect(screen.queryByText("bob@example.com")).toBeNull();
  });

  it("shows no-match message when filters exclude all users", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    await act(async () => render(<UsersPanel />));
    fireEvent.change(screen.getByTestId("email-search"), { target: { value: "zzz" } });
    expect(screen.getByText("No users match your filters.")).toBeTruthy();
  });

  it("opens confirm dialog when Delete clicked", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    await act(async () => render(<UsersPanel />));

    const deleteButtons = screen.getAllByText("Delete");
    await act(async () => fireEvent.click(deleteButtons[0]));

    expect(screen.getByText("Delete user?")).toBeTruthy();
  });

  it("deletes user on confirm and removes row", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.deleteUser.mockResolvedValue(null);
    await act(async () => render(<UsersPanel />));

    const deleteButtons = screen.getAllByText("Delete");
    await act(async () => fireEvent.click(deleteButtons[0]));

    // Confirm in the dialog — last "Delete" button is the confirm
    await act(async () => fireEvent.click(screen.getAllByText("Delete").at(-1)));

    expect(api.deleteUser).toHaveBeenCalledWith("u1");
    await waitFor(() => expect(screen.queryByText("alice@example.com")).toBeNull());
  });

  it("does not delete when dialog is cancelled", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    await act(async () => render(<UsersPanel />));

    const deleteButtons = screen.getAllByText("Delete");
    await act(async () => fireEvent.click(deleteButtons[0]));
    await act(async () => fireEvent.click(screen.getByText("Cancel")));

    expect(api.deleteUser).not.toHaveBeenCalled();
    expect(screen.getByText("alice@example.com")).toBeTruthy();
  });

  it("shows error when delete fails", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.deleteUser.mockRejectedValue(new Error("Delete failed"));
    await act(async () => render(<UsersPanel />));

    const deleteButtons = screen.getAllByText("Delete");
    await act(async () => fireEvent.click(deleteButtons[0]));
    await act(async () => fireEvent.click(screen.getAllByText("Delete").at(-1)));

    await waitFor(() => expect(screen.getByText("Delete failed")).toBeTruthy());
  });

  it("shows Load more button when has_more is true", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS, has_more: true, next_cursor: "tok1" });
    await act(async () => render(<UsersPanel />));
    expect(screen.getByText("Load more")).toBeTruthy();
  });

  it("does not show Load more button when has_more is false", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS, has_more: false });
    await act(async () => render(<UsersPanel />));
    expect(screen.queryByText("Load more")).toBeNull();
  });

  it("loads more users on button click", async () => {
    const extra = [{
      user_id: "u3",
      email: "carol@example.com",
      display_name: "Carol",
      role: "user",
      created_at: "2026-03-01T00:00:00Z",
      last_login_at: "2026-04-03T00:00:00Z",
    }];
    api.listUsers
      .mockResolvedValueOnce({ items: SAMPLE_USERS, has_more: true, next_cursor: "tok1" })
      .mockResolvedValueOnce({ items: extra, has_more: false, next_cursor: null });
    await act(async () => render(<UsersPanel />));
    await act(async () => fireEvent.click(screen.getByText("Load more")));
    expect(screen.getByText("carol@example.com")).toBeTruthy();
  });

  it("opens detail panel when row is clicked", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.getUserStats.mockResolvedValue({ user_id: "u1", memory_count: 5, client_count: 2 });
    await act(async () => render(<UsersPanel />));
    await act(async () => fireEvent.click(screen.getByText("alice@example.com")));
    expect(screen.getByTestId("user-detail")).toBeTruthy();
    expect(screen.getByText("Alice")).toBeTruthy();
  });

  it("shows stats in detail panel", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.getUserStats.mockResolvedValue({ user_id: "u1", memory_count: 5, client_count: 2 });
    await act(async () => render(<UsersPanel />));
    await act(async () => fireEvent.click(screen.getByText("alice@example.com")));
    await waitFor(() => expect(screen.getByText("Memories")).toBeTruthy());
    expect(screen.getByText("Clients")).toBeTruthy();
  });

  it("hides stats section when getUserStats fails", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.getUserStats.mockRejectedValue(new Error("Stats unavailable"));
    await act(async () => render(<UsersPanel />));
    await act(async () => fireEvent.click(screen.getByText("alice@example.com")));
    await waitFor(() => expect(screen.queryByText("Memories")).toBeNull());
  });

  it("closes detail panel on X click", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.getUserStats.mockResolvedValue({ user_id: "u1", memory_count: 0, client_count: 0 });
    await act(async () => render(<UsersPanel />));
    await act(async () => fireEvent.click(screen.getByText("alice@example.com")));
    await act(async () => fireEvent.click(screen.getByLabelText("Close detail panel")));
    expect(screen.queryByTestId("user-detail")).toBeNull();
  });

  it("updates role when changed in detail panel", async () => {
    const updatedAlice = { ...SAMPLE_USERS[0], role: "user" };
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.getUserStats.mockResolvedValue({ user_id: "u1", memory_count: 0, client_count: 0 });
    api.updateUserRole.mockResolvedValue(updatedAlice);
    await act(async () => render(<UsersPanel />));
    await act(async () => fireEvent.click(screen.getByText("alice@example.com")));
    const detailPanel = screen.getByTestId("user-detail");
    const roleSelect = detailPanel.querySelector("select");
    await act(async () => fireEvent.change(roleSelect, { target: { value: "user" } }));
    expect(api.updateUserRole).toHaveBeenCalledWith("u1", "user");
  });

  it("shows error when role update fails", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.getUserStats.mockResolvedValue({ user_id: "u1", memory_count: 0, client_count: 0 });
    api.updateUserRole.mockRejectedValue(new Error("Role update failed"));
    await act(async () => render(<UsersPanel />));
    await act(async () => fireEvent.click(screen.getByText("alice@example.com")));
    const detailPanel = screen.getByTestId("user-detail");
    const roleSelect = detailPanel.querySelector("select");
    await act(async () => fireEvent.change(roleSelect, { target: { value: "user" } }));
    await waitFor(() => expect(screen.getByText("Role update failed")).toBeTruthy());
  });

  it("opens delete dialog from detail panel delete button", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.getUserStats.mockResolvedValue({ user_id: "u1", memory_count: 0, client_count: 0 });
    await act(async () => render(<UsersPanel />));
    await act(async () => fireEvent.click(screen.getByText("alice@example.com")));
    await act(async () => fireEvent.click(screen.getByText("Delete user")));
    expect(screen.getByText("Delete user?")).toBeTruthy();
  });

  it("closes detail panel after deleting from it", async () => {
    api.listUsers.mockResolvedValue({ items: SAMPLE_USERS });
    api.getUserStats.mockResolvedValue({ user_id: "u1", memory_count: 0, client_count: 0 });
    api.deleteUser.mockResolvedValue(null);
    await act(async () => render(<UsersPanel />));
    await act(async () => fireEvent.click(screen.getByText("alice@example.com")));
    await act(async () => fireEvent.click(screen.getByText("Delete user")));
    // Confirm
    await act(async () => fireEvent.click(screen.getAllByText("Delete").at(-1)));
    await waitFor(() => expect(screen.queryByTestId("user-detail")).toBeNull());
  });
});
