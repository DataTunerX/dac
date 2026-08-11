export const REFRESH_CHAT_LIST_EVENT = "dac:chat_list_refresh"

/** Emitted when backend returns a different run_id than the client optimistic id. */
export const RUN_ID_RECONCILED_EVENT = "dac:run_id_reconciled"

export type NewChatEventDetail = {
  id: string
  title: string
  created_at: string
  // Optional: when backend returns a new run_id and we want to replace the optimistic one.
  replace_id?: string
}

export type RunIdReconciledDetail = {
  oldId: string
  newId: string
}

