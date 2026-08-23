import { apiRequest } from "./client";
import type { ImageAnalysis } from "./types";

export function analyzeImage(payload: {
  file: File;
  equipmentType?: string;
  equipmentId?: string;
  question?: string;
}): Promise<ImageAnalysis> {
  const form = new FormData();
  form.append("file", payload.file);
  if (payload.equipmentType) form.append("equipment_type", payload.equipmentType);
  if (payload.equipmentId) form.append("equipment_id", payload.equipmentId);
  if (payload.question) form.append("question", payload.question);
  return apiRequest("/api/v1/images/analyze", { method: "POST", body: form, isFormData: true });
}

export function getImageAnalysis(id: string): Promise<ImageAnalysis> {
  return apiRequest(`/api/v1/images/${id}`);
}
