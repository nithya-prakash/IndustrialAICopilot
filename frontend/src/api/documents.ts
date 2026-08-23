import { apiRequest } from "./client";
import type { DocumentSummary } from "./types";

export function listDocuments(): Promise<{ documents: DocumentSummary[] }> {
  return apiRequest("/api/v1/documents");
}

export function getDocument(id: string): Promise<DocumentSummary> {
  return apiRequest(`/api/v1/documents/${id}`);
}

export function uploadDocument(payload: {
  file: File;
  equipmentType?: string;
  equipmentId?: string;
}): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", payload.file);
  if (payload.equipmentType) form.append("equipment_type", payload.equipmentType);
  if (payload.equipmentId) form.append("equipment_id", payload.equipmentId);
  return apiRequest("/api/v1/documents/upload", { method: "POST", body: form, isFormData: true });
}

export function deleteDocument(id: string): Promise<void> {
  return apiRequest(`/api/v1/documents/${id}`, { method: "DELETE" });
}
