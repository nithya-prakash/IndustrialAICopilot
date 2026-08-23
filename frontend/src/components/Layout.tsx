import type { CSSProperties, ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const NAV_LINK_STYLE: CSSProperties = {
  display: "block",
  padding: "9px 14px",
  borderRadius: 8,
  fontSize: 13,
  fontWeight: 550,
};

export function Layout() {
  const { user, logout } = useAuth();
  const canApprove = user?.role === "supervisor" || user?.role === "admin";
  const isAdmin = user?.role === "admin";

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <aside
        style={{
          width: 220,
          flexShrink: 0,
          background: "var(--color-nav-bg)",
          color: "var(--color-nav-text)",
          padding: "20px 14px",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        <div style={{ padding: "0 10px 20px" }}>
          <div style={{ color: "white", fontWeight: 700, fontSize: 15, lineHeight: 1.3 }}>
            Industrial AI Copilot
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-faint)", marginTop: 4 }}>
            {user?.tenant_id}
          </div>
        </div>

        <NavItem to="/">Dashboard</NavItem>
        <NavItem to="/knowledge-base">Knowledge Base</NavItem>
        <NavItem to="/copilot">AI Copilot</NavItem>
        {canApprove && <NavItem to="/approvals">Approvals</NavItem>}
        {isAdmin && <NavItem to="/audit-log">Audit Log</NavItem>}

        <div style={{ marginTop: "auto", padding: "14px 10px 0", borderTop: "1px solid #1e293b" }}>
          <div style={{ color: "white", fontSize: 13, fontWeight: 600 }}>{user?.username}</div>
          <div style={{ fontSize: 11, color: "var(--color-text-faint)", marginBottom: 10 }}>
            {user?.role}
          </div>
          <button
            className="btn btn-secondary btn-sm"
            style={{ width: "100%" }}
            onClick={logout}
          >
            Sign out
          </button>
        </div>
      </aside>

      <main style={{ flex: 1, padding: "28px 36px", maxWidth: 1180, margin: "0 auto" }}>
        <Outlet />
      </main>
    </div>
  );
}

function NavItem({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      style={({ isActive }) => ({
        ...NAV_LINK_STYLE,
        background: isActive ? "rgba(255,255,255,0.1)" : "transparent",
        color: isActive ? "var(--color-nav-text-active)" : "var(--color-nav-text)",
      })}
    >
      {children}
    </NavLink>
  );
}
