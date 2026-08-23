import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import * as diagnosesApi from "../api/diagnoses";
import type { Diagnosis } from "../api/types";
import { ConfidenceBadge, SeverityBadge } from "../components/Badges";

export function ApprovalsPage() {
  const [pending, setPending] = useState<Diagnosis[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    diagnosesApi
      .listDiagnoses({ pending_approval: true })
      .then(setPending)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load"));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function decide(id: string, decision: "approve" | "reject") {
    setBusyId(id);
    setError(null);
    try {
      const comments = commentDrafts[id]?.trim() || undefined;
      if (decision === "approve") {
        await diagnosesApi.approveDiagnosis(id, comments);
      } else {
        await diagnosesApi.rejectDiagnosis(id, comments);
      }
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Decision failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div>
        <h1>Approval Dashboard</h1>
        <p style={{ color: "var(--color-text-muted)", marginTop: 4 }}>
          Diagnoses flagged for human review before technicians act on them.
        </p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {pending === null && <p style={{ color: "var(--color-text-muted)" }}>Loading…</p>}
      {pending?.length === 0 && (
        <div className="card">
          <div className="empty-state">Nothing pending review right now.</div>
        </div>
      )}

      <div className="stack" style={{ gap: 16 }}>
        {pending?.map((d) => (
          <div key={d.id} className="card card-pad stack" style={{ gap: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div>
                <Link to={`/diagnoses/${d.id}`} style={{ fontWeight: 600, fontSize: 15, color: "var(--color-text)" }}>
                  {d.question}
                </Link>
                <div style={{ fontSize: 12, color: "var(--color-text-faint)", marginTop: 3 }}>
                  {d.equipment_id && <>{d.equipment_id} · </>}
                  {new Date(d.created_at).toLocaleString()}
                </div>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <SeverityBadge severity={d.severity} />
                <ConfidenceBadge confidence={d.confidence} />
              </div>
            </div>

            <p style={{ fontSize: 13, color: "var(--color-text-muted)" }}>{d.summary}</p>

            {d.possible_causes.length > 0 && (
              <div style={{ fontSize: 13 }}>
                <strong>Top cause:</strong> {[...d.possible_causes].sort((a, b) => a.rank - b.rank)[0]?.cause}
              </div>
            )}

            <div className="field">
              <label>Comments (optional)</label>
              <textarea
                rows={2}
                value={commentDrafts[d.id] ?? ""}
                onChange={(e) => setCommentDrafts((prev) => ({ ...prev, [d.id]: e.target.value }))}
                placeholder="Add context for this decision…"
              />
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                className="btn btn-success"
                onClick={() => decide(d.id, "approve")}
                disabled={busyId === d.id}
              >
                Approve
              </button>
              <button
                className="btn btn-danger"
                onClick={() => decide(d.id, "reject")}
                disabled={busyId === d.id}
              >
                Reject
              </button>
              <Link to={`/diagnoses/${d.id}`} className="btn btn-secondary" style={{ marginLeft: "auto" }}>
                Inspect evidence
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
