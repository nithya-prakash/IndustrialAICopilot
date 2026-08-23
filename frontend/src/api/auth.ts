import { apiRequest } from "./client";
import type { TokenResponse, UserRole } from "./types";

export function register(payload: {
  username: string;
  email: string;
  password: string;
  role?: UserRole;
  tenant_id?: string;
}): Promise<TokenResponse> {
  return apiRequest<TokenResponse>("/api/v1/auth/register", { method: "POST", body: payload });
}

export function login(payload: { username: string; password: string }): Promise<TokenResponse> {
  return apiRequest<TokenResponse>("/api/v1/auth/login", { method: "POST", body: payload });
}
