export type UserRole = "technician" | "supervisor" | "admin";

export interface User {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  tenant_id: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export type DocumentStatus =
  | "uploaded"
  | "processing"
  | "extracting"
  | "ocr"
  | "chunking"
  | "embedding"
  | "indexing"
  | "ready"
  | "failed";

export interface DocumentSummary {
  id: string;
  original_filename: string;
  equipment_type: string | null;
  equipment_id: string | null;
  version_number: number | null;
  status: DocumentStatus | null;
  error_message: string | null;
  page_count: number | null;
  used_ocr: boolean | null;
  chunk_count: number;
  created_at: string;
}

export type ImageAnalysisStatus = "analyzing" | "ready" | "failed";

export interface Observation {
  description: string;
  confidence: number;
}

export interface ImageAnalysis {
  id: string;
  status: ImageAnalysisStatus;
  equipment_type: string | null;
  equipment_id: string | null;
  vision_provider: string;
  vision_model: string;
  observations: Observation[];
  limitations: string[];
  error_message: string | null;
  created_at: string;
}

export interface SensorReadingItem {
  id: string;
  equipment_id: string;
  metric: string;
  value: number;
  unit: string | null;
  recorded_at: string;
}

export interface Cause {
  cause: string;
  rank: number;
  supporting_citations: string[];
}

export interface Evidence {
  type: string;
  citation: string;
  detail: string;
}

export type DiagnosisStatus = "completed" | "failed";
export type Severity = "low" | "medium" | "high" | "critical";

export interface Approval {
  id: string;
  decision: "approved" | "rejected";
  supervisor_id: string;
  comments: string | null;
  created_at: string;
}

export interface Diagnosis {
  id: string;
  conversation_id: string;
  status: DiagnosisStatus;
  error_message: string | null;
  equipment_id: string | null;
  equipment_type: string | null;
  question: string;
  summary: string | null;
  visual_observations: Observation[];
  sensor_findings: { metric?: string; finding?: string }[];
  possible_causes: Cause[];
  recommended_checks: string[];
  recommended_action: string | null;
  confidence: number;
  severity: Severity;
  requires_human_approval: boolean;
  evidence: Evidence[];
  limitations: string[];
  llm_provider: string;
  llm_model: string;
  created_at: string;
  approval: Approval | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  diagnosis_id: string | null;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  equipment_id: string | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: Message[];
}

export interface AuditLogEntry {
  id: string;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface HealthStatus {
  status: string;
  checks: Record<string, string>;
}
