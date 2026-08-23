import { apiRequest } from "./client";
import type { Diagnosis } from "./types";

export function queryCopilot(payload: {
  question: string;
  conversationId?: string;
  equipmentId?: string;
  equipmentType?: string;
  imageAnalysisId?: string;
  sensorReadings?: Record<string, number>;
}): Promise<Diagnosis> {
  return apiRequest("/api/v1/copilot/query", {
    method: "POST",
    body: {
      question: payload.question,
      conversation_id: payload.conversationId,
      equipment_id: payload.equipmentId,
      equipment_type: payload.equipmentType,
      image_analysis_id: payload.imageAnalysisId,
      sensor_readings: payload.sensorReadings,
    },
  });
}
