import type { ChatProgressPayload } from "@/lib/api-types"
import type { ExecutionFlowTask } from "@/lib/execution-flow"

/** Single message in the conversation. Assistant messages may carry frozen progress once the stream ends. */
export interface ChatMessage {
  id?: string
  role: "user" | "assistant" | "system"
  content: string
  reasoning_content?: string
  progressList?: readonly ChatProgressPayload[]
  executionFlowList?: readonly ExecutionFlowTask[]
}

/** Stable empty array for progress list (rerender-best-practice). */
export const EMPTY_PROGRESS: readonly ChatProgressPayload[] = []

/** API response shape for GET /api/v1/chat/conversations/:runId (history). */
export interface ConversationHistoryResponse {
  messages?: Array<{
    role?: string
    content?: string
    think?: string
    reasoning_content?: string
    progress_list?: Array<Record<string, unknown>>
  }>
}
