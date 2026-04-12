// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import EmptyState from "./EmptyState.jsx";
import { AlertDialog } from "./ui/alert-dialog.jsx";
import { Button } from "./ui/button.jsx";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table.jsx";

export default function UsersPanel() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listUsers();
      setUsers(data ? data.items : []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDelete(userId) {
    try {
      await api.deleteUser(userId);
      setUsers((prev) => prev.filter((u) => u.user_id !== userId));
    } catch (e) {
      setError(e.message);
    } finally {
      setPendingDelete(null);
    }
  }

  if (loading) return <p>Loading…</p>;
  if (error) return <p className="text-[var(--danger)]">{error}</p>;

  return (
    <div>
      <AlertDialog
        open={pendingDelete !== null}
        title="Delete user?"
        description="This will permanently remove the user account."
        onConfirm={() => handleDelete(pendingDelete)}
        onCancel={() => setPendingDelete(null)}
      />

      <h2 className="mb-4 font-semibold text-lg">Users</h2>
      {users.length === 0 ? (
        <EmptyState
          variant="users"
          title="No users found"
          description="Users appear here after they sign in for the first time via Google OAuth."
        />
      ) : (
        <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Last Login</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((u) => (
              <TableRow key={u.user_id}>
                <TableCell>{u.email}</TableCell>
                <TableCell>{u.role}</TableCell>
                <TableCell>{new Date(u.last_login_at).toLocaleString()}</TableCell>
                <TableCell>
                  <Button variant="danger" size="sm" onClick={() => setPendingDelete(u.user_id)}>
                    Delete
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        </div>
      )}
    </div>
  );
}
