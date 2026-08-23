import type { ReactNode } from "react";
import type { Diagnosis } from "../api/types";
import {
  ApprovalBadge,
  ConfidenceBadge,
  DiagnosisStatusBadge,
  SeverityBadge,
} from "./Badges";

export function DiagnosisView({ diagnosis }: { diagnosis: Diagnosis }) {
  if (diagnosis.status === "failed") {
    return (
      <div className="card card-pad stack" style={{ gap: 12 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <DiagnosisStatusBadge status={diagnosis.status} />
          <ApprovalBadge
            requiresApproval={diagnosis.requires_human_approval}
            decision={diagnosis.approval?.decision}
          />
        </div>
        <div className="error-banner">
          The diagnosis could not be completed: {diagnosis.error_message}
        </div>
      </div>
    );
  }

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="card card-pad stack" style={{ gap: 14 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <DiagnosisStatusBadge status={diagnosis.status} />
          <SeverityBadge severity={diagnosis.severity} />
          <ConfidenceBadge confidence={diagnosis.confidence} />
          <ApprovalBadge
            requiresApproval={diagnosis.requires_human_approval}
            decision={diagnosis.approval?.decision}
          />
        </div>

        {diagnosis.requires_human_approval && !diagnosis.approval && (
          <div className="error-banner" style={{ background: "var(--color-warning-soft)", color: "var(--color-warning)", borderColor: "var(--color-warning-border)" }}>
            ⚠ Human review recommended before acting on this diagnosis.
          </div>
        )}

        <Section title="Summary">
          <p>{diagnosis.summary}</p>
        </Section>

        {diagnosis.visual_observations.length > 0 && (
          <Section title="Visual Observations">
            <ul className="stack" style={{ gap: 6, paddingLeft: 18, margin: 0 }}>
              {diagnosis.visual_observations.map((obs, i) => (
                <li key={i}>
                  {obs.description}{" "}
                  <span style={{ color: "var(--color-text-faint)" }}>
                    ({Math.round(obs.confidence * 100)}%)
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {diagnosis.sensor_findings.length > 0 && (
          <Section title="Sensor Findings">
            <ul className="stack" style={{ gap: 6, paddingLeft: 18, margin: 0 }}>
              {diagnosis.sensor_findings.map((f, i) => (
                <li key={i}>{f.finding ?? JSON.stringify(f)}</li>
              ))}
            </ul>
          </Section>
        )}

        {diagnosis.possible_causes.length > 0 && (
          <Section title="Possible Causes">
            <ol className="stack" style={{ gap: 8, paddingLeft: 18, margin: 0 }}>
              {[...diagnosis.possible_causes]
                .sort((a, b) => a.rank - b.rank)
                .map((cause, i) => (
                  <li key={i}>
                    {cause.cause}
                    {cause.supporting_citations.length > 0 && (
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                        {cause.supporting_citations.map((c, j) => (
                          <span key={j} className="mono badge badge-info">
                            {c}
                          </span>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
            </ol>
          </Section>
        )}

        {diagnosis.recommended_checks.length > 0 && (
          <Section title="Recommended Checks">
            <ul className="stack" style={{ gap: 6, paddingLeft: 18, margin: 0 }}>
              {diagnosis.recommended_checks.map((check, i) => (
                <li key={i}>{check}</li>
              ))}
            </ul>
          </Section>
        )}

        {diagnosis.recommended_action && (
          <Section title="Recommended Action">
            <p>{diagnosis.recommended_action}</p>
          </Section>
        )}

        {diagnosis.limitations.length > 0 && (
          <Section title="Limitations">
            <ul
              className="stack"
              style={{ gap: 6, paddingLeft: 18, margin: 0, color: "var(--color-text-muted)" }}
            >
              {diagnosis.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          </Section>
        )}

        {diagnosis.approval && (
          <Section title="Approval Decision">
            <p>
              <strong>{diagnosis.approval.decision === "approved" ? "Approved" : "Rejected"}</strong>
              {" — "}
              {new Date(diagnosis.approval.created_at).toLocaleString()}
            </p>
            {diagnosis.approval.comments && (
              <p style={{ color: "var(--color-text-muted)", marginTop: 4 }}>
                “{diagnosis.approval.comments}”
              </p>
            )}
          </Section>
        )}
      </div>

      {diagnosis.evidence.length > 0 && (
        <div className="card card-pad stack" style={{ gap: 10 }}>
          <h3>Evidence</h3>
          <div className="stack" style={{ gap: 10 }}>
            {diagnosis.evidence.map((e, i) => (
              <div
                key={i}
                style={{
                  padding: "10px 12px",
                  background: "var(--color-surface-alt)",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--color-border)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <span className="badge badge-neutral">{e.type.replace("_", " ")}</span>
                  <span className="mono" style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                    {e.citation}
                  </span>
                </div>
                {e.detail && (
                  <p style={{ marginTop: 6, color: "var(--color-text-muted)", fontSize: 13 }}>
                    {e.detail}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 style={{ marginBottom: 6, color: "var(--color-text-muted)" }}>{title}</h3>
      {children}
    </div>
  );
}
