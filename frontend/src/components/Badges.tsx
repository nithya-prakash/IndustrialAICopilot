import type { DiagnosisStatus, DocumentStatus, ImageAnalysisStatus, Severity } from "../api/types";

export function SeverityBadge({ severity }: { severity: Severity }) {
  const cls =
    severity === "critical" || severity === "high"
      ? "badge-danger"
      : severity === "medium"
        ? "badge-warning"
        : "badge-neutral";
  return <span className={`badge ${cls}`}>{severity}</span>;
}

export function ConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const cls = confidence >= 0.75 ? "badge-success" : confidence >= 0.5 ? "badge-warning" : "badge-danger";
  return <span className={`badge ${cls}`}>Confidence: {pct}%</span>;
}

const DOCUMENT_STATUS_CLASS: Record<DocumentStatus, string> = {
  uploaded: "badge-neutral",
  processing: "badge-info",
  extracting: "badge-info",
  ocr: "badge-info",
  chunking: "badge-info",
  embedding: "badge-info",
  indexing: "badge-info",
  ready: "badge-success",
  failed: "badge-danger",
};

export function DocumentStatusBadge({ status }: { status: DocumentStatus | null }) {
  if (!status) return <span className="badge badge-neutral">unknown</span>;
  return <span className={`badge ${DOCUMENT_STATUS_CLASS[status]}`}>{status}</span>;
}

const IMAGE_STATUS_CLASS: Record<ImageAnalysisStatus, string> = {
  analyzing: "badge-info",
  ready: "badge-success",
  failed: "badge-danger",
};

export function ImageStatusBadge({ status }: { status: ImageAnalysisStatus }) {
  return <span className={`badge ${IMAGE_STATUS_CLASS[status]}`}>{status}</span>;
}

export function DiagnosisStatusBadge({ status }: { status: DiagnosisStatus }) {
  return (
    <span className={`badge ${status === "completed" ? "badge-success" : "badge-danger"}`}>
      {status}
    </span>
  );
}

export function ApprovalBadge({
  requiresApproval,
  decision,
}: {
  requiresApproval: boolean;
  decision: "approved" | "rejected" | null | undefined;
}) {
  if (decision === "approved") return <span className="badge badge-success">Approved</span>;
  if (decision === "rejected") return <span className="badge badge-danger">Rejected</span>;
  if (requiresApproval) return <span className="badge badge-warning">Pending approval</span>;
  return <span className="badge badge-neutral">No approval required</span>;
}
