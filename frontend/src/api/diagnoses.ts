import { apiRequest } from "./client";
import type { Diagnosis } from "./types";

export function listDiagnoses(params?: {
  equipment_id?: string;
  pending_approval?: boolean;
}): Promise<Diagnosis[]> {
  return apiRequest("/api/v1/diagnoses", { params });
}

export function getDiagnosis(id: string): Promise<Diagnosis> {
  return apiRequest(`/api/v1/diagnoses/${id}`);
}

export function getDiagnosisReport(id: string): Promise<string> {
  return apiRequest(`/api/v1/diagnoses/${id}/report`);
}

export function approveDiagnosis(id: string, comments?: string): Promise<Diagnosis> {
  return apiRequest(`/api/v1/diagnoses/${id}/approve`, { method: "POST", body: { comments } });
}

export function rejectDiagnosis(id: string, comments?: string): Promise<Diagnosis> {
  return apiRequest(`/api/v1/diagnoses/${id}/reject`, { method: "POST", body: { comments } });
}
