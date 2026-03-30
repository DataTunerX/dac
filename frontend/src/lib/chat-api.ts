/**
 * Typed API for chat (conversations). Uses @/lib/api; response interceptor unwraps envelope.
 */
import { api } from "@/lib/api"
import type { ListConversationsResponse } from "@/lib/api-types"

export interface ListConversationsOptions {
  days?: number
}

export async function listConversations(options: ListConversationsOptions = {}): Promise<ListConversationsResponse> {
  const res = await api.get<ListConversationsResponse>("/chat/conversations", {
    params: typeof options.days === "number" ? { days: options.days } : undefined,
  })
  return res.data
}
