import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../api/client";
import type { User, UserRole } from "../api/types";
import * as usersApi from "../api/users";
import { useAuth } from "../context/AuthContext";

const ROLES: UserRole[] = ["technician", "supervisor", "admin"];

export function UsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("technician");
  const [isSaving, setIsSaving] = useState(false);

  function reportError(err: unknown, fallback: string) {
    setError(err instanceof ApiError ? err.message : fallback);
  }

  useEffect(() => {
    usersApi
      .listUsers()
      .then(setUsers)
      .catch((err) => reportError(err, "Failed to load users"));
  }, []);

  function replaceUser(updated: User) {
    setUsers((current) => current?.map((u) => (u.id === updated.id ? updated : u)) ?? null);
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSaving(true);
    try {
      const created = await usersApi.createUser({ username, email, password, role });
      setUsers((current) => [...(current ?? []), created]);
      setUsername("");
      setEmail("");
      setPassword("");
      setRole("technician");
    } catch (err) {
      reportError(err, "Failed to add user");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleUpdate(id: string, changes: { role?: UserRole; is_active?: boolean }) {
    setError(null);
    try {
      replaceUser(await usersApi.updateUser(id, changes));
    } catch (err) {
      reportError(err, "Failed to update user");
    }
  }

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div>
        <h1>Users</h1>
        <p style={{ color: "var(--color-text-muted)", marginTop: 4 }}>
          People in the <strong>{me?.tenant_id}</strong> workspace. Adding someone here is the only
          way into this workspace.
        </p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="card card-pad">
        <h2 style={{ marginBottom: 14 }}>Add a user</h2>
        <form
          onSubmit={handleCreate}
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
            gap: 12,
            alignItems: "end",
          }}
        >
          <div className="field">
            <label>Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              pattern="[a-zA-Z0-9_.\-]+"
              minLength={3}
              maxLength={64}
              required
            />
          </div>
          <div className="field">
            <label>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field">
            <label>Initial password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>
          <div className="field">
            <label>Role</label>
            <select value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          <button className="btn btn-primary" type="submit" disabled={isSaving}>
            {isSaving ? "Adding…" : "Add user"}
          </button>
        </form>
      </div>

      <div className="card card-pad">
        {users === null && !error && <p style={{ color: "var(--color-text-muted)" }}>Loading…</p>}
        {users && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr
                style={{
                  textAlign: "left",
                  color: "var(--color-text-muted)",
                  fontSize: 11,
                  textTransform: "uppercase",
                }}
              >
                <th style={{ padding: "6px 8px" }}>Username</th>
                <th style={{ padding: "6px 8px" }}>Email</th>
                <th style={{ padding: "6px 8px" }}>Role</th>
                <th style={{ padding: "6px 8px" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isMe = u.id === me?.id;
                return (
                  <tr key={u.id} style={{ borderTop: "1px solid var(--color-border)" }}>
                    <td style={{ padding: "8px", fontWeight: 600 }}>
                      {u.username}
                      {isMe && (
                        <span style={{ color: "var(--color-text-faint)", fontWeight: 400 }}> (you)</span>
                      )}
                    </td>
                    <td style={{ padding: "8px", color: "var(--color-text-muted)" }}>{u.email}</td>
                    <td style={{ padding: "8px" }}>
                      {/* An admin can't demote themselves (the backend refuses it too). */}
                      <select
                        value={u.role}
                        disabled={isMe}
                        onChange={(e) => handleUpdate(u.id, { role: e.target.value as UserRole })}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td style={{ padding: "8px" }}>
                      {isMe ? (
                        <span className="badge badge-neutral">active</span>
                      ) : (
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleUpdate(u.id, { is_active: !u.is_active })}
                        >
                          {u.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
