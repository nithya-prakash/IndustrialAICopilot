import { apiRequest } from "./client";
import type { User, UserRole } from "./types";

// Admin-only, always scoped to the admin's own workspace on the backend.
export function listUsers(): Promise<User[]> {
  return apiRequest("/api/v1/users");
}

export function createUser(payload: {
  username: string;
  email: string;
  password: string;
  role: UserRole;
}): Promise<User> {
  return apiRequest("/api/v1/users", { method: "POST", body: payload });
}

export function updateUser(
  id: string,
  changes: { role?: UserRole; is_active?: boolean }
): Promise<User> {
  return apiRequest(`/api/v1/users/${id}`, { method: "PATCH", body: changes });
}
