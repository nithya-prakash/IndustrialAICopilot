import { apiRequest } from "./client";
import type { ConversationDetail, ConversationSummary } from "./types";

export function listConversations(): Promise<ConversationSummary[]> {
  return apiRequest("/api/v1/conversations");
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return apiRequest(`/api/v1/conversations/${id}`);
}
