export const REFRESH_CHAT_LIST_EVENT = "dac:chat_list_refresh"

export type NewChatEventDetail = {
  id: string
  title: string
  created_at: string
  // Optional: when backend returns a new run_id and we want to replace the optimistic one.
  replace_id?: string
}

