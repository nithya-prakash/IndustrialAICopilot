import { apiRequest } from "./client";
import type { SensorReadingItem } from "./types";

export function uploadSensorSnapshot(payload: {
  equipmentId: string;
  equipmentType?: string;
  readings: Record<string, number>;
}): Promise<{ readings: SensorReadingItem[] }> {
  return apiRequest("/api/v1/sensors/upload", {
    method: "POST",
    body: {
      equipment_id: payload.equipmentId,
      equipment_type: payload.equipmentType,
      readings: payload.readings,
    },
  });
}

export interface SensorAnalysis {
  equipment_id: string;
  metric: string;
  unit: string | null;
  reading_count: number;
  summary: {
    count: number;
    mean: number;
    median: number;
    std_dev: number;
    min_value: number;
    max_value: number;
  } | null;
  trend: { direction: string; slope_per_hour: number; r_squared: number } | null;
  anomalies: { recorded_at: string; value: number; score: number; method: string }[];
  threshold_violations: {
    recorded_at: string;
    value: number;
    limit_min: number | null;
    limit_max: number | null;
    source: string | null;
  }[];
  baseline_comparison: Record<string, unknown> | null;
}

export function getSensorAnalysis(
  equipmentId: string,
  params: { metric: string; start_time: string; end_time: string }
): Promise<SensorAnalysis> {
  return apiRequest(`/api/v1/sensors/${equipmentId}/analysis`, { params });
}
