import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import type { UserRole } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { AuthLayout } from "./LoginPage";

export function RegisterPage() {
  const { user, register, isLoading } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("technician");
  const [tenantId, setTenantId] = useState("default");
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to="/" replace />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await register(username, email, password, role, tenantId);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
    }
  }

  return (
    <AuthLayout>
      <h1>Create account</h1>
      <p style={{ color: "var(--color-text-muted)", marginTop: 4, marginBottom: 20 }}>
        Industrial Multimodal AI Copilot
      </p>
      <form onSubmit={handleSubmit} className="stack" style={{ gap: 14 }}>
        {error && <div className="error-banner">{error}</div>}
        <div className="field">
          <label>Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div className="field">
          <label>Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div className="field">
          <label>Password</label>
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
            <option value="technician">Technician</option>
            <option value="supervisor">Supervisor</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div className="field">
          <label>Company / tenant</label>
          <input value={tenantId} onChange={(e) => setTenantId(e.target.value)} required />
        </div>
        <button className="btn btn-primary" type="submit" disabled={isLoading}>
          {isLoading ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p style={{ marginTop: 18, fontSize: 13, color: "var(--color-text-muted)" }}>
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
