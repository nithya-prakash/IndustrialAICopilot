import { apiRequest } from "./client";
import type { AuditLogEntry } from "./types";

export function listAuditLogs(params?: {
  resource_type?: string;
  resource_id?: string;
}): Promise<AuditLogEntry[]> {
  return apiRequest("/api/v1/audit-logs", { params });
}
