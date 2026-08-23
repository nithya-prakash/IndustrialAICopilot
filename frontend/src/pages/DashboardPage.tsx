import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import * as diagnosesApi from "../api/diagnoses";
import * as documentsApi from "../api/documents";
import * as healthApi from "../api/health";
import type { Diagnosis, DocumentSummary, HealthStatus } from "../api/types";
import { ApprovalBadge, ConfidenceBadge, DocumentStatusBadge, SeverityBadge } from "../components/Badges";
import { useAuth } from "../context/AuthContext";

export function DashboardPage() {
  const { user } = useAuth();
  const canApprove = user?.role === "supervisor" || user?.role === "admin";

  const [diagnoses, setDiagnoses] = useState<Diagnosis[] | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[] | null>(null);
  const [pending, setPending] = useState<Diagnosis[] | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    diagnosesApi.listDiagnoses().then(setDiagnoses).catch(() => setDiagnoses([]));
    documentsApi.listDocuments().then((r) => setDocuments(r.documents)).catch(() => setDocuments([]));
    healthApi.getHealth().then(setHealth).catch(() => setHealth(null));
    if (canApprove) {
      diagnosesApi
        .listDiagnoses({ pending_approval: true })
        .then(setPending)
        .catch(() => setPending([]));
    }
  }, [canApprove]);

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div>
        <h1>Dashboard</h1>
        <p style={{ color: "var(--color-text-muted)", marginTop: 4 }}>
          Overview of recent diagnostics, documentation, and system status.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
        <StatCard label="Diagnoses" value={diagnoses?.length} />
        <StatCard label="Manuals indexed" value={documents?.filter((d) => d.status === "ready").length} />
        <StatCard label="Pending approvals" value={canApprove ? pending?.length : undefined} muted={!canApprove} />
        <StatCard
          label="System status"
          value={health ? health.status : undefined}
          isText
          tone={health?.status === "ok" ? "success" : "danger"}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 20, alignItems: "start" }}>
        <div className="card card-pad">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h2>Recent diagnoses</h2>
            <Link to="/copilot" style={{ fontSize: 13 }}>
              New query →
            </Link>
          </div>
          {diagnoses === null && <p style={{ color: "var(--color-text-muted)" }}>Loading…</p>}
          {diagnoses?.length === 0 && <div className="empty-state">No diagnoses yet.</div>}
          <div className="stack" style={{ gap: 10 }}>
            {diagnoses?.slice(0, 6).map((d) => (
              <Link
                key={d.id}
                to={`/diagnoses/${d.id}`}
                style={{
                  display: "block",
                  padding: "10px 12px",
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--color-text)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <span style={{ fontWeight: 550, fontSize: 13 }}>
                    {d.question.length > 60 ? d.question.slice(0, 60) + "…" : d.question}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--color-text-faint)", whiteSpace: "nowrap" }}>
                    {new Date(d.created_at).toLocaleDateString()}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                  {d.status === "completed" ? (
                    <>
                      <SeverityBadge severity={d.severity} />
                      <ConfidenceBadge confidence={d.confidence} />
                      <ApprovalBadge
                        requiresApproval={d.requires_human_approval}
                        decision={d.approval?.decision}
                      />
                    </>
                  ) : (
                    <span className="badge badge-danger">failed</span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        </div>

        <div className="card card-pad">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h2>Document status</h2>
            <Link to="/knowledge-base" style={{ fontSize: 13 }}>
              Manage →
            </Link>
          </div>
          {documents === null && <p style={{ color: "var(--color-text-muted)" }}>Loading…</p>}
          {documents?.length === 0 && <div className="empty-state">No manuals uploaded yet.</div>}
          <div className="stack" style={{ gap: 10 }}>
            {documents?.slice(0, 6).map((doc) => (
              <div key={doc.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 13 }}>{doc.original_filename}</span>
                <DocumentStatusBadge status={doc.status} />
              </div>
            ))}
          </div>
        </div>
      </div>

      {canApprove && pending && pending.length > 0 && (
        <div className="card card-pad">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h2>Pending your approval</h2>
            <Link to="/approvals" style={{ fontSize: 13 }}>
              Review all →
            </Link>
          </div>
          <div className="stack" style={{ gap: 10 }}>
            {pending.slice(0, 4).map((d) => (
              <Link
                key={d.id}
                to={`/diagnoses/${d.id}`}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "10px 12px",
                  border: "1px solid var(--color-warning-border)",
                  background: "var(--color-warning-soft)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--color-text)",
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 550 }}>{d.question}</span>
                <SeverityBadge severity={d.severity} />
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  muted,
  isText,
  tone,
}: {
  label: string;
  value: number | string | undefined;
  muted?: boolean;
  isText?: boolean;
  tone?: "success" | "danger";
}) {
  return (
    <div className="card card-pad">
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.03em" }}>
        {label}
      </div>
      <div
        style={{
          fontSize: isText ? 18 : 28,
          fontWeight: 700,
          marginTop: 6,
          color: muted
            ? "var(--color-text-faint)"
            : tone === "success"
              ? "var(--color-success)"
              : tone === "danger"
                ? "var(--color-danger)"
                : "var(--color-text)",
        }}
      >
        {value === undefined ? (muted ? "—" : <span className="spinner" />) : value}
      </div>
    </div>
  );
}
