import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import * as documentsApi from "../api/documents";
import { ApiError } from "../api/client";
import type { DocumentSummary } from "../api/types";
import { DocumentStatusBadge } from "../components/Badges";

const PROCESSING_STATUSES = new Set([
  "uploaded",
  "processing",
  "extracting",
  "ocr",
  "chunking",
  "embedding",
  "indexing",
]);

export function KnowledgeBasePage() {
  const [documents, setDocuments] = useState<DocumentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [equipmentType, setEquipmentType] = useState("");
  const [equipmentId, setEquipmentId] = useState("");

  const refresh = useCallback(() => {
    documentsApi
      .listDocuments()
      .then((r) => setDocuments(r.documents))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load documents"));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll while any document is still processing, so status updates without a manual refresh.
  useEffect(() => {
    const hasInFlight = documents?.some((d) => d.status && PROCESSING_STATUSES.has(d.status));
    if (!hasInFlight) return;
    const timer = setInterval(refresh, 2500);
    return () => clearInterval(timer);
  }, [documents, refresh]);

  async function handleUpload(e: FormEvent) {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await documentsApi.uploadDocument({
        file,
        equipmentType: equipmentType || undefined,
        equipmentId: equipmentId || undefined,
      });
      if (fileInputRef.current) fileInputRef.current.value = "";
      setEquipmentType("");
      setEquipmentId("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this manual? This cannot be undone.")) return;
    try {
      await documentsApi.deleteDocument(id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div>
        <h1>Knowledge Base</h1>
        <p style={{ color: "var(--color-text-muted)", marginTop: 4 }}>
          Upload equipment manuals and technical documentation for the diagnosis agent to search.
        </p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="card card-pad">
        <h2 style={{ marginBottom: 14 }}>Upload manual</h2>
        <form onSubmit={handleUpload} style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="field" style={{ flex: "1 1 220px" }}>
            <label>PDF file</label>
            <input ref={fileInputRef} type="file" accept="application/pdf" required />
          </div>
          <div className="field" style={{ width: 160 }}>
            <label>Equipment type</label>
            <input
              value={equipmentType}
              onChange={(e) => setEquipmentType(e.target.value)}
              placeholder="electric_motor"
            />
          </div>
          <div className="field" style={{ width: 160 }}>
            <label>Equipment ID</label>
            <input
              value={equipmentId}
              onChange={(e) => setEquipmentId(e.target.value)}
              placeholder="MOTOR-001"
            />
          </div>
          <button className="btn btn-primary" type="submit" disabled={uploading}>
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </form>
      </div>

      <div className="card card-pad">
        <h2 style={{ marginBottom: 14 }}>Manuals</h2>
        {documents === null && <p style={{ color: "var(--color-text-muted)" }}>Loading…</p>}
        {documents?.length === 0 && <div className="empty-state">No manuals uploaded yet.</div>}
        {documents && documents.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--color-text-muted)", fontSize: 11, textTransform: "uppercase" }}>
                <th style={{ padding: "6px 8px" }}>Filename</th>
                <th style={{ padding: "6px 8px" }}>Equipment</th>
                <th style={{ padding: "6px 8px" }}>Version</th>
                <th style={{ padding: "6px 8px" }}>Status</th>
                <th style={{ padding: "6px 8px" }}>Chunks</th>
                <th style={{ padding: "6px 8px" }}></th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id} style={{ borderTop: "1px solid var(--color-border)" }}>
                  <td style={{ padding: "10px 8px", fontWeight: 550 }}>{doc.original_filename}</td>
                  <td style={{ padding: "10px 8px", color: "var(--color-text-muted)" }}>
                    {doc.equipment_id || doc.equipment_type ? (
                      <>
                        {doc.equipment_id}
                        {doc.equipment_type && (
                          <span style={{ color: "var(--color-text-faint)" }}> · {doc.equipment_type}</span>
                        )}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td style={{ padding: "10px 8px" }}>v{doc.version_number ?? "—"}</td>
                  <td style={{ padding: "10px 8px" }}>
                    <DocumentStatusBadge status={doc.status} />
                    {doc.status === "failed" && doc.error_message && (
                      <div style={{ fontSize: 11, color: "var(--color-danger)", marginTop: 3 }}>
                        {doc.error_message}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "10px 8px" }}>{doc.chunk_count}</td>
                  <td style={{ padding: "10px 8px", textAlign: "right" }}>
                    <button className="btn btn-secondary btn-sm" onClick={() => handleDelete(doc.id)}>
                      Delete
                    </button>
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
