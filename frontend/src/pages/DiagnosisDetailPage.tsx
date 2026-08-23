import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import * as diagnosesApi from "../api/diagnoses";
import type { Diagnosis } from "../api/types";
import { DiagnosisView } from "../components/DiagnosisView";
import { useAuth } from "../context/AuthContext";

export function DiagnosisDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const canApprove = user?.role === "supervisor" || user?.role === "admin";

  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [comments, setComments] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!id) return;
    diagnosesApi
      .getDiagnosis(id)
      .then(setDiagnosis)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load diagnosis"));
  }, [id]);

  async function decide(decision: "approve" | "reject") {
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      const updated =
        decision === "approve"
          ? await diagnosesApi.approveDiagnosis(id, comments.trim() || undefined)
          : await diagnosesApi.rejectDiagnosis(id, comments.trim() || undefined);
      setDiagnosis(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return <div className="error-banner">{error}</div>;
  }
  if (!diagnosis) {
    return <p style={{ color: "var(--color-text-muted)" }}>Loading…</p>;
  }

  const canDecide =
    canApprove &&
    diagnosis.status === "completed" &&
    diagnosis.requires_human_approval &&
    !diagnosis.approval;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <Link to="/" style={{ fontSize: 13 }}>
          ← Back
        </Link>
        <h1 style={{ marginTop: 8 }}>{diagnosis.question}</h1>
      </div>

      <DiagnosisView diagnosis={diagnosis} />

      {canDecide && (
        <div className="card card-pad stack" style={{ gap: 12 }}>
          <h2>Supervisor decision</h2>
          <div className="field">
            <label>Comments</label>
            <textarea rows={2} value={comments} onChange={(e) => setComments(e.target.value)} />
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn btn-success" onClick={() => decide("approve")} disabled={busy}>
              Approve
            </button>
            <button className="btn btn-danger" onClick={() => decide("reject")} disabled={busy}>
              Reject
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
