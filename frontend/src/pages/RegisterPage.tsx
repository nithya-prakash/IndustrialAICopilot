import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { AuthLayout } from "./LoginPage";

export function RegisterPage() {
  const { user, register, isLoading } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to="/" replace />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await register(username, email, password, tenantId);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
    }
  }

  return (
    <AuthLayout>
      <h1>Create a workspace</h1>
      <p style={{ color: "var(--color-text-muted)", marginTop: 4, marginBottom: 20 }}>
        Industrial Multimodal AI Copilot
      </p>
      <form onSubmit={handleSubmit} className="stack" style={{ gap: 14 }}>
        {error && <div className="error-banner">{error}</div>}
        <div className="field">
          <label>Username</label>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            pattern="[a-zA-Z0-9_.\-]+"
            minLength={3}
            maxLength={64}
            title="Letters, numbers, underscores, dots, and hyphens only — no spaces"
            required
          />
          <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Letters, numbers, underscores, dots, and hyphens only — no spaces
          </span>
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
          <label>Company workspace ID</label>
          <input
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            pattern="[a-zA-Z0-9_.\-]+"
            maxLength={64}
            placeholder="e.g. acme-plant-1"
            required
          />
          <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Creates a new workspace with you as its admin. Joining an existing workspace? Ask its
            admin to add you.
          </span>
        </div>
        <button className="btn btn-primary" type="submit" disabled={isLoading}>
          {isLoading ? "Creating workspace…" : "Create workspace"}
        </button>
      </form>
      <p style={{ marginTop: 18, fontSize: 13, color: "var(--color-text-muted)" }}>
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
