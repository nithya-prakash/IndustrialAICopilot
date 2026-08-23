import { apiRequest } from "./client";
import type { HealthStatus } from "./types";

export function getHealth(): Promise<HealthStatus> {
  return apiRequest("/api/v1/health");
}
