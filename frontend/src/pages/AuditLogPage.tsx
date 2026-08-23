import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import * as auditApi from "../api/audit";
import type { AuditLogEntry } from "../api/types";

export function AuditLogPage() {
  const [logs, setLogs] = useState<AuditLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    auditApi
      .listAuditLogs()
      .then(setLogs)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load audit log"));
  }, []);

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div>
        <h1>Audit Log</h1>
        <p style={{ color: "var(--color-text-muted)", marginTop: 4 }}>
          Append-only record of diagnosis and document lifecycle events.
        </p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="card card-pad">
        {logs === null && <p style={{ color: "var(--color-text-muted)" }}>Loading…</p>}
        {logs?.length === 0 && <div className="empty-state">No events recorded yet.</div>}
        {logs && logs.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--color-text-muted)", fontSize: 11, textTransform: "uppercase" }}>
                <th style={{ padding: "6px 8px" }}>Time</th>
                <th style={{ padding: "6px 8px" }}>Action</th>
                <th style={{ padding: "6px 8px" }}>Resource</th>
                <th style={{ padding: "6px 8px" }}>Detail</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} style={{ borderTop: "1px solid var(--color-border)" }}>
                  <td style={{ padding: "8px", color: "var(--color-text-faint)", whiteSpace: "nowrap" }}>
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                  <td style={{ padding: "8px" }}>
                    <span className="badge badge-neutral">{log.action}</span>
                  </td>
                  <td style={{ padding: "8px" }} className="mono">
                    {log.resource_type}/{log.resource_id.slice(0, 8)}
                  </td>
                  <td style={{ padding: "8px", color: "var(--color-text-muted)" }}>
                    {Object.keys(log.detail).length > 0 ? JSON.stringify(log.detail) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
