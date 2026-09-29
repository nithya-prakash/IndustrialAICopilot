import { apiRequest } from "./client";
import type { TokenResponse } from "./types";

// Sign-up always creates a NEW company workspace, with the caller as its
// admin — there is no role field and no way to join an existing workspace
// here. Other users are added by that admin (see api/users.ts).
export function register(payload: {
  username: string;
  email: string;
  password: string;
  tenant_id: string;
}): Promise<TokenResponse> {
  return apiRequest<TokenResponse>("/api/v1/auth/register", { method: "POST", body: payload });
}

export function login(payload: { username: string; password: string }): Promise<TokenResponse> {
  return apiRequest<TokenResponse>("/api/v1/auth/login", { method: "POST", body: payload });
}
